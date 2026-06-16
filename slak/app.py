# slak — Terminal Slack client
# Copyright (C) 2026 Toni Leino
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""The slak Textual application (multi-workspace shell).

Non-modal: the compose box is focused on launch, so you just type. Tab moves
focus; the command palette (Ctrl+P) is the action surface; Alt+1..9 switch
workspaces. The active workspace is read from the router at call time, so
switching is just moving a pointer.
"""

from __future__ import annotations

import os
import re
import sys
import time
import webbrowser
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, ListView, Static

from slak.cache import Cache, Channel, ThreadSubscription
from slak.debuglog import debug
from slak.emoji import resolve_custom_emoji
from slak.blockkit import image_urls
from slak.images import EmojiImages, MediaImages, detect_protocol, tmux_passthrough
from slak.links import extract_links
from slak.nav import NavHistory
from slak.text import fold
from slak.config import Config
from slak.notify import (
    DesktopNotifier,
    Notifier,
    NotifyContext,
    notification_text,
    should_notify,
)
from slak.services import (
    backfill,
    format_mpdm,
    persist_messages,
    to_remote_message,
    translate_mentions,
    typing_text,
    window_title,
)
from slak.slack import (
    Connected,
    DndChanged,
    MessageDeleted,
    MessageEdited,
    NewMessage,
    PresenceChanged,
    ReactionUpdated,
    SectionsChanged,
    SlackClient,
    StarsChanged,
    Typing,
)
from slak.ui.commands import PyslkCommands
from slak.ui.widgets import (
    ChannelFinder,
    ComposeInput,
    EditModal,
    HelpModal,
    LinkPicker,
    MultiUserPicker,
    MentionPopup,
    MessagePane,
    Rail,
    ReactionModal,
    SearchBar,
    SearchResultsModal,
    Sidebar,
    ThemePicker,
    ThreadList,
    ThreadPanel,
    WorkspaceSwitcher,
)
from slak.ui.widgets import THREADS_ROW_ID
from slak.sections import layout as section_layout, order_native_sections
from slak.mcp import build_snapshot, default_socket_path, message_dict, serve as serve_mcp
from slak import themes
from slak.workspace import WorkspaceRouter


class PyslkApp(App):
    CSS_PATH = Path(__file__).parent / "ui" / "styles" / "app.tcss"
    TITLE = "slak"
    COMMANDS = App.COMMANDS | {PyslkCommands}
    BINDINGS = [
        Binding(f"alt+{n}", f"switch_workspace({n - 1})", show=False)
        for n in range(1, 10)
    ] + [
        Binding("escape", "focus_compose", show=False),
        Binding("enter", "open_thread", show=False),
        Binding("ctrl+t", "toggle_thread", show=False),
        Binding("ctrl+b", "toggle_sidebar", show=False),
        Binding("ctrl+k", "find_channel", show=False, priority=True),
        Binding("ctrl+w", "switch_workspace_overlay", show=False, priority=True),
        Binding("alt+left", "history_back", show=False),
        Binding("alt+right", "history_forward", show=False),
        Binding("f1", "help", show=False, priority=True),
        Binding("ctrl+r", "react", show=False),
        Binding("ctrl+y", "pick_theme", show=False),
        Binding("ctrl+shift+y", "pick_default_theme", show=False),
        Binding("ctrl+n", "new_message", show=False),
        Binding("ctrl+e", "edit_message", show=False, priority=True),
        Binding("ctrl+o", "open_links", show=False),
        Binding("ctrl+f", "search", show=False),
        Binding("ctrl+shift+f", "search_workspace", show=False),
    ]

    def __init__(
        self,
        router: WorkspaceRouter,
        cache: Cache,
        config: Config,
        notifier: Notifier | None = None,
        url_opener: Callable[[str], object] | None = None,
        config_path: Path | None = None,
    ):
        # Set before super().__init__(): Textual reads get_css_variables() during
        # App init, which needs the active theme name + any inline overrides.
        self._theme_name = config.theme  # active colour theme (spec 05 §2)
        self.config = config
        super().__init__()
        self.router = router
        self.cache = cache
        self._notifier = notifier or DesktopNotifier()
        self._open_url = url_opener or webbrowser.open
        self._config_path = config_path
        self.active_channel: str | None = None
        self._nav: dict[str, NavHistory] = {}  # team_id -> channel back/forward
        self._channel_names: dict[str, str] = {}
        self._chan_meta: dict[str, dict[str, tuple[str, str]]] = {}  # team->cid->(name,type)
        self._names: dict[str, dict[str, str]] = {}  # team_id -> {user_id: display}
        self._handles: dict[str, dict[str, str]] = {}  # team_id -> {handle: display}
        self._custom_emoji: dict[str, dict[str, str]] = {}  # team_id -> {name: url}
        self._emoji_images: EmojiImages | None = None
        self._media_images: MediaImages | None = None
        self._resolving: set[tuple[str, str]] = set()
        self.open_thread_ts: str = ""
        self.open_thread_channel: str = ""
        self._view: str = "channels"  # "channels" | "threads" (spec 03 §8)
        self._collapsed_sections: dict[str, set[str]] = {}  # team_id -> names
        self._native_sections: dict[str, list] = {}  # team_id -> [RemoteSection]
        self._stars: dict[str, set[str]] = {}  # team_id -> starred channel ids
        self._sidebar_channels: list = []  # active workspace's channels
        self._last_backfill: dict[str, float] = {}  # team_id -> monotonic ts
        self._search_matches: list[str] = []
        self._search_idx: int = 0
        self._presence: dict[str, tuple[str, float]] = {}  # team -> (presence, dnd_end)
        self._typing: dict[str, float] = {}  # user_id -> expiry (monotonic)
        self._typing_timer = None
        self._last_typing_sent: float = 0.0  # monotonic, for ≥3s throttle
        self._completion_active: bool = False
        self._completion_at: int = -1
        self._completion_kind: str = ""  # "@" or ":"

    @property
    def client(self) -> SlackClient | None:
        return self.router.active()

    def get_css_variables(self) -> dict[str, str]:
        # Feed the active colour theme's slots in as CSS variables so app.tcss
        # can reference $bg/$surface/$accent/… (spec 05 §2).
        variables = super().get_css_variables()
        variables.update(themes.theme_variables(self._theme_name))
        # [theme] inline per-slot overrides win (spec 05 §custom)
        for slot, value in self.config.theme_overrides.items():
            variables[slot.replace("_", "-")] = value
        return variables

    def _apply_theme(self, name: str) -> None:
        self._theme_name = name
        self.refresh_css(animate=False)

    def _persist_config(self) -> None:
        """Write config to disk if a path was provided (no-op otherwise)."""
        if self._config_path is None:
            return
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(self.config.dumps())
        except OSError as exc:
            self.log(f"config save failed: {exc!r}")

    def compose(self) -> ComposeResult:
        yield Rail(id="rail")
        with Horizontal():
            yield Sidebar(id="sidebar")
            with Vertical(id="main"):
                yield Static("", id="header")
                yield Static("─" * 200, id="header-rule")
                yield MessagePane(id="messages")
                yield ThreadList(id="threads")
                yield Static("", id="typing")
                yield SearchBar(placeholder="Search this channel…", id="search")
                yield MentionPopup(id="completion-popup")
                yield ComposeInput(placeholder="Message…", id="compose")
            yield ThreadPanel(id="thread")
        yield Static("", id="status")

    async def on_mount(self) -> None:
        self._init_emoji_images()
        for pane_id in ("#messages", "#thread-messages"):
            try:
                pane = self.query_one(pane_id, MessagePane)
                pane.set_custom_render(self._custom_render)
                pane.set_image_render(self._image_render)
            except Exception:
                pass
        self.query_one("#threads", ThreadList).set_custom_render(self._custom_render)
        self.query_one("#threads", ThreadList).display = False
        self.query_one("#typing", Static).display = False
        self._typing_timer = self.set_interval(1, self._prune_typing, pause=True)
        self._refresh_rail()
        await self._load_active_workspace()
        self.query_one("#compose", Input).focus()
        for client in self.router.all():
            if client is not self.client:
                self.run_worker(self._seed_channels(client), exclusive=False)
            self.run_worker(self._consume_events(client), exclusive=False)
            if hasattr(client, "start_realtime"):
                self.run_worker(self._run_realtime(client), exclusive=False)
        self.set_interval(60, self._update_status)  # DND countdown refresh
        if self.config.mcp_enabled:
            self.run_worker(self._serve_mcp(), exclusive=False)

    async def _seed_channels(self, client: SlackClient) -> None:
        """Populate the cache with a workspace's channels so cross-workspace
        unread state has rows to update before the workspace is ever opened."""
        try:
            channels = await client.list_channels()
        except Exception as exc:
            self.log(f"channel seed failed for {client.team_id}: {exc!r}")
            return
        self._upsert_channels(client.team_id, channels)
        self._refresh_rail()

    # --- workspaces -------------------------------------------------------

    def _refresh_rail(self) -> None:
        order = self.router.ordered()
        initials = [_initials(self.router.client(t).team_name) for t in order]
        active = self.router.active_team_id()
        active_idx = order.index(active) if active in order else 0
        unread_ws = set(self.cache.workspaces_with_unreads())
        flags = [t in unread_ws for t in order]
        self.query_one("#rail", Rail).set_workspaces(initials, active_idx, flags)
        self._refresh_title()

    def _refresh_title(self) -> None:
        active = self.router.active_team_id()
        if active is None:
            self.title = "slak"
            return
        client = self.router.client(active)
        initials = _initials(client.team_name) if client else ""
        state = self.cache.get_workspace_read_state(active)
        active_count = sum(1 for s in state.values() if s.has_unread)
        others = sum(1 for t in self.cache.workspaces_with_unreads() if t != active)
        self.title = window_title(initials, active_count, others)

    def _refresh_sidebar_unread(self) -> None:
        active = self.router.active_team_id()
        if active is None:
            return
        state = self.cache.get_workspace_read_state(active)
        unread = {cid for cid, s in state.items() if s.has_unread}
        self.query_one("#sidebar", Sidebar).set_unread(unread)

    def _upsert_channels(self, team_id: str, channels) -> None:
        meta = self._chan_meta.setdefault(team_id, {})
        for ch in channels:
            self.cache.upsert_channel(
                Channel(id=ch.id, workspace_id=team_id, name=ch.name, type=ch.type)
            )
            meta[ch.id] = (ch.name, ch.type)

    def _maybe_notify(self, client: SlackClient, event: NewMessage) -> None:
        cfg = self.config
        if not cfg.notify_enabled:
            return
        _, dnd_end = self._presence.get(client.team_id, ("auto", 0.0))
        if dnd_end > time.time():
            return  # suppressed while Do Not Disturb is active
        msg = event.message
        name, ctype = self._chan_meta.get(client.team_id, {}).get(
            event.channel_id, (event.channel_id, "channel")
        )
        is_dm = ctype in ("dm", "group_dm")
        ctx = NotifyContext(
            enabled=cfg.notify_enabled,
            on_mention=cfg.notify_on_mention,
            on_dm=cfg.notify_on_dm,
            keywords=cfg.notify_keywords,
            is_dm=is_dm,
            is_active_channel=client is self.client
            and event.channel_id == self.active_channel,
            is_self=bool(client.self_user_id) and msg.user_id == client.self_user_id,
            text=msg.text,
            self_user_id=client.self_user_id,
        )
        if not should_notify(ctx):
            return
        sender = self._names.get(client.team_id, {}).get(msg.user_id, msg.user_id)
        label = sender if is_dm else f"#{name}"
        title, body = notification_text(client.team_name, label, sender, msg.text)
        self._notifier.notify(title, body)

    async def action_switch_workspace(self, index: int) -> None:
        if self.router.set_active_index(index):
            self._refresh_rail()
            await self._load_active_workspace()

    def action_switch_workspace_overlay(self) -> None:
        self.run_worker(self._switch_workspace_flow(), exclusive=False)

    async def _switch_workspace_flow(self) -> None:
        items = []
        for team_id in self.router.ordered():
            client = self.router.client(team_id)
            name = client.team_name if client else team_id
            items.append(SimpleNamespace(id=team_id, name=name))
        team_id = await self.push_screen_wait(WorkspaceSwitcher(items))
        if team_id and self.router.set_active(team_id):
            self._refresh_rail()
            await self._load_active_workspace()

    def action_pick_theme(self) -> None:
        self.run_worker(self._pick_theme_flow(default=False), exclusive=False)

    def action_pick_default_theme(self) -> None:
        self.run_worker(self._pick_theme_flow(default=True), exclusive=False)

    async def _pick_theme_flow(self, default: bool) -> None:
        team = self.router.active_team_id()
        if team is None:
            return
        client = self.router.client(team)
        label = (
            "Default theme for new workspaces"
            if default
            else f"Theme for {client.team_name if client else team}"
        )
        name = await self.push_screen_wait(
            ThemePicker(themes.theme_names(), placeholder=label)
        )
        if not name:
            return
        if default:
            self.config.set_default_theme(name)
            if self.config.resolve_theme(team) == name:
                self._apply_theme(name)
        else:
            self.config.set_workspace_theme(team, name, self.config.slug_for(team))
            self._apply_theme(name)
        self._persist_config()

    def action_new_message(self) -> None:
        self.run_worker(self._new_message_flow(), exclusive=False)

    async def _new_message_flow(self) -> None:
        client = self.client
        if client is None:
            return
        users = [
            u
            for u in await client.list_users()
            if u.id != client.self_user_id and not u.deleted
        ]
        selected = await self.push_screen_wait(MultiUserPicker(users))
        if not selected:
            return
        channel = await client.open_conversation(selected)
        if not channel.name:
            names = self._names.get(client.team_id, {})
            channel.name = ", ".join(names.get(u, u) for u in selected)
        self._upsert_channels(client.team_id, [channel])
        self._channel_names[channel.id] = channel.name
        # reflect the new conversation in the sidebar, then open it
        self.query_one("#sidebar", Sidebar).add_channel(channel)
        await self.open_channel(channel.id)

    async def _load_active_workspace(self) -> None:
        client = self.client
        if client is None:
            return
        self._apply_theme(self.config.resolve_theme(client.team_id))
        await self._load_users(client)
        await self._load_custom_emoji(client)
        channels = await client.list_channels()
        self._resolve_dm_names(client.team_id, channels)
        self._channel_names = {ch.id: ch.name for ch in channels}
        self._upsert_channels(client.team_id, channels)
        self._sidebar_channels = channels
        await self._load_native_sections(client)
        await self._load_stars(client)
        await self._load_unreads(client)
        await self._populate_sidebar()
        await self._load_thread_subscriptions(client)
        self.active_channel = None
        if channels:
            await self.open_channel(channels[0].id)
        else:
            self.query_one("#messages", MessagePane).set_messages([], self._name_of)
        self._refresh_sidebar_unread()
        self._update_status()

    def _resolve_dm_names(self, team_id: str, channels) -> None:
        """Give DM/MPIM channels human names — peer display name for a 1:1 DM,
        formatted member list for a group DM (spec/slk parity)."""
        names = self._names.get(team_id, {})
        handles = self._handles.get(team_id, {})
        for ch in channels:
            if ch.type == "dm" and ch.user and not ch.name:
                ch.name = names.get(ch.user, ch.user)
            elif ch.type == "group_dm":
                ch.name = format_mpdm(ch.name, handles.get)

    # --- channels ---------------------------------------------------------

    def _nav_for(self, team_id: str) -> NavHistory:
        return self._nav.setdefault(team_id, NavHistory())

    def _valid_channels(self, team_id: str) -> set[str]:
        return set(self._chan_meta.get(team_id, {}))

    async def action_history_back(self) -> None:
        team = self.router.active_team_id()
        if team is None:
            return
        channel_id = self._nav_for(team).back(self._valid_channels(team))
        if channel_id:
            await self.open_channel(channel_id, record_history=False)

    async def action_history_forward(self) -> None:
        team = self.router.active_team_id()
        if team is None:
            return
        channel_id = self._nav_for(team).forward(self._valid_channels(team))
        if channel_id:
            await self.open_channel(channel_id, record_history=False)

    async def _load_native_sections(self, client: SlackClient) -> None:
        """Fetch Slack-native sidebar sections once at workspace load (spec 03 §9)."""
        if not self.config.uses_slack_sections(client.team_id):
            return
        try:
            sections = await client.list_channel_sections()
        except Exception as exc:
            self.log(f"channel sections fetch failed: {exc!r}")
            return
        # set unconditionally (even []) so a later emptying clears stale sections
        self._native_sections[client.team_id] = sections

    async def _reload_sections(self, client: SlackClient) -> None:
        await self._load_native_sections(client)
        if client is self.client:
            await self._populate_sidebar()

    async def _load_unreads(self, client: SlackClient) -> None:
        """Seed startup unread state from Slack (client.counts) so channels with
        new messages show as unread before any live event arrives."""
        try:
            ids = await client.list_unread_channels()
        except Exception as exc:
            self.log(f"unread counts fetch failed: {exc!r}")
            return
        for cid in ids:
            self.cache.set_channel_unread(cid, True)

    async def _load_stars(self, client: SlackClient) -> None:
        try:
            stars = await client.list_stars()
        except Exception as exc:
            self.log(f"stars fetch failed: {exc!r}")
            return
        self._stars[client.team_id] = set(stars)

    async def _reload_stars(self, client: SlackClient) -> None:
        await self._load_stars(client)
        if client is self.client:
            await self._populate_sidebar()

    # --- typing indicators (inbound, spec 04 §9) --------------------------

    def _on_typing(self, client: SlackClient, event: Typing) -> None:
        if not self.config.typing_indicators:
            return
        if client is not self.client or event.channel_id != self.active_channel:
            return
        if event.user_id == client.self_user_id:
            return
        self._typing[event.user_id] = time.monotonic() + 5.0
        self._render_typing()
        if self._typing_timer is not None:
            self._typing_timer.resume()

    def _prune_typing(self) -> None:
        now = time.monotonic()
        expired = [u for u, exp in self._typing.items() if exp <= now]
        for u in expired:
            del self._typing[u]
        self._render_typing()
        if not self._typing and self._typing_timer is not None:
            self._typing_timer.pause()

    def _render_typing(self) -> None:
        names = [self._name_of(u) for u in self._typing]
        text = typing_text(names)
        widget = self.query_one("#typing", Static)
        widget.update(text)
        widget.display = bool(text)

    def _native_groups(self, sections, channels):
        """Group channels under Slack-native sections (mirrors slk).

        A channel explicitly in a section's ``channel_ids`` goes there; any other
        channel falls into the default section for its type (DMs → direct_messages,
        else → channels) rather than a generic bucket. Empty non-standard sections
        are hidden; standard (custom) sections always render."""
        ordered = order_native_sections(sections)
        explicit: dict[str, str] = {}
        for s in sections:
            for cid in s.channel_ids:
                explicit.setdefault(cid, s.id)

        def first_id(section_type: str) -> str:
            return next((s.id for s in ordered if s.type == section_type), "")

        dm_id, channels_id = first_id("direct_messages"), first_id("channels")

        def section_of(ch) -> str:
            if ch.id in explicit:
                return explicit[ch.id]
            if ch.type in ("dm", "group_dm"):
                return dm_id or channels_id
            return channels_id

        buckets: dict[str, list] = {s.id: [] for s in ordered}
        ungrouped = []
        for ch in channels:
            sid = section_of(ch)
            (buckets[sid] if sid in buckets else ungrouped).append(ch)

        groups = []
        for s in ordered:
            if s.type != "standard" and not buckets[s.id]:
                continue  # hide empty Channels/DMs/Apps; keep empty custom sections
            label = f"{s.emoji} {s.name}".strip() if s.emoji else s.name
            groups.append((label, buckets[s.id]))
        if ungrouped:
            groups.append((None, ungrouped))
        return groups

    async def _populate_sidebar(self) -> None:
        """Render the sidebar — a pinned ★ Starred section (if any), then
        Slack-native sections, else config-glob sections, else a flat list.
        Starred channels appear only in the Starred section (spec 03 §9)."""
        team = self.router.active_team_id() or ""
        sidebar = self.query_one("#sidebar", Sidebar)
        collapsed = self._collapsed_sections.setdefault(team, set())
        starred = self._stars.get(team, set())
        rest = [c for c in self._sidebar_channels if c.id not in starred]

        native = self._native_sections.get(team)
        section_names = list(self.config.sections_for(team))
        if native:
            groups = self._native_groups(native, rest)
        elif section_names:
            groups = section_layout(
                section_names, lambda n: self.config.match_section(team, n), rest
            )
        else:
            # flat: only need an ungrouped bucket when a Starred section forces grouping
            star_chans = [c for c in self._sidebar_channels if c.id in starred]
            groups = [(None, rest)] if star_chans else []

        star_chans = [c for c in self._sidebar_channels if c.id in starred]
        if star_chans:
            groups = [("★ Starred", star_chans)] + groups

        if groups:
            await sidebar.set_sections(groups, collapsed)
        else:
            await sidebar.set_channels(rest)

    async def _toggle_section(self, name: str) -> None:
        team = self.router.active_team_id() or ""
        collapsed = self._collapsed_sections.setdefault(team, set())
        collapsed ^= {name}
        await self._populate_sidebar()
        self._refresh_sidebar_unread()

    async def _load_thread_subscriptions(self, client: SlackClient) -> None:
        try:
            subs = await client.list_thread_subscriptions()
        except Exception as exc:
            self.log(f"thread subscriptions fetch failed: {exc!r}")
            return
        self.cache.reconcile_thread_subscriptions(
            client.team_id,
            [
                ThreadSubscription(client.team_id, s.channel_id, s.thread_ts, s.last_read)
                for s in subs
            ],
        )

    async def _enter_threads_view(self) -> None:
        team = self.router.active_team_id()
        if team is None:
            return
        self._view = "threads"
        self.query_one("#header", Static).update("⚑ Threads")
        self.query_one("#messages", MessagePane).display = False
        self.query_one("#search", SearchBar).display = False
        self.query_one("#compose", Input).display = False
        threads = self.query_one("#threads", ThreadList)
        threads.display = True
        threads.set_threads(self.cache.threads_overview(team), self._name_of)
        threads.focus()

    def _exit_threads_view(self) -> None:
        if self._view != "threads":
            return
        self._view = "channels"
        self.query_one("#threads", ThreadList).display = False
        self.query_one("#messages", MessagePane).display = True
        self.query_one("#compose", Input).display = True

    async def open_channel(self, channel_id: str, record_history: bool = True) -> None:
        client = self.client
        if client is None:
            return
        self._exit_threads_view()
        if channel_id != self.active_channel:
            self._typing.clear()
            self._render_typing()
        self.active_channel = channel_id
        if record_history and (team := self.router.active_team_id()) is not None:
            self._nav_for(team).visit(channel_id)
        name = self._channel_names.get(channel_id, channel_id)
        self.query_one("#header", Static).update(f"#{name}")
        # cache-first: render what we have instantly…
        cached = [to_remote_message(m) for m in self.cache.get_messages(channel_id)]
        self.query_one("#messages", MessagePane).set_messages(
            _top_level(cached), self._name_of
        )
        # opening a channel marks it read
        latest_ts = cached[-1].ts if cached else ""
        self.cache.update_read_state(channel_id, latest_ts, has_unread=False)
        self._refresh_sidebar_unread()
        self._refresh_rail()
        self._update_status()
        # …then reconcile against Slack in the background.
        self.run_worker(self._sync_channel(client, channel_id), exclusive=False)
        self.run_worker(self._prefetch_emoji(), exclusive=False)
        self.run_worker(self._prefetch_images(), exclusive=False)

    async def _sync_channel(self, client: SlackClient, channel_id: str) -> None:
        try:
            fetched = await client.history(channel_id)
        except Exception as exc:
            self.log(f"history fetch failed for {channel_id}: {exc!r}")
            return
        persist_messages(self.cache, client.team_id, channel_id, fetched)
        if self.client is client and self.active_channel == channel_id:
            self.query_one("#messages", MessagePane).set_messages(
                _top_level(fetched), self._name_of
            )
            self.run_worker(self._prefetch_emoji(), exclusive=False)
            self.run_worker(self._prefetch_images(), exclusive=False)

    async def _load_users(self, client: SlackClient) -> None:
        try:
            users = await client.list_users()
        except Exception as exc:
            self.log(f"user list failed for {client.team_id}: {exc!r}")
            return
        self._names[client.team_id] = {u.id: u.name for u in users}
        self._handles[client.team_id] = {
            u.handle: u.name for u in users if u.handle
        }

    async def _load_custom_emoji(self, client: SlackClient) -> None:
        try:
            customs = await client.list_custom_emoji()
        except Exception as exc:
            self.log(f"custom emoji fetch failed for {client.team_id}: {exc!r}")
            return
        self._custom_emoji[client.team_id] = customs
        if client is self.client:
            self._refresh_messages()
            self.run_worker(self._prefetch_emoji(), exclusive=False)
            self.run_worker(self._prefetch_images(), exclusive=False)

    # --- custom emoji images (kitty, best-effort) ------------------------

    def _init_emoji_images(self) -> None:
        if self.config.emoji_images == "off":
            proto = "off"  # disabled -> custom emoji render as :name: text
        else:
            proto = self.config.image_protocol
            if proto == "auto":
                proto = detect_protocol(dict(os.environ))
        cache_dir = Path.home() / ".cache" / "slak" / "emoji"
        self._emoji_images = EmojiImages(
            proto, self._fetch_image, cache_dir, self._emit_raw
        )
        media_proto = self.config.image_protocol
        if media_proto == "auto":
            media_proto = detect_protocol(dict(os.environ))
        self._media_images = MediaImages(
            media_proto, self._fetch_image,
            Path.home() / ".cache" / "slak" / "media", self._emit_raw,
        )
        debug(f"init emoji images: protocol={proto} enabled={self._emoji_images.enabled}")

    async def _fetch_image(self, url: str) -> bytes:
        # Slack `url_private` files need the workspace auth; the active client
        # fetches authed. Public CDN URLs (emoji) work either way.
        client = self.client
        fetch_bytes = getattr(client, "fetch_bytes", None)
        if fetch_bytes is not None:
            return await fetch_bytes(url)
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            return resp.content

    def _emit_raw(self, seq: str) -> None:
        if os.environ.get("TMUX"):
            seq = tmux_passthrough(seq)
        # Route through Textual's own writer thread so the kitty upload is
        # serialized with frame output on the SAME stream (stderr). A raw
        # os.write to stdout races Textual's writer and corrupts the APC.
        driver = getattr(self, "_driver", None)
        if driver is not None:
            try:
                driver.write(seq)
                driver.flush()
                debug(f"emit via driver: {len(seq)} bytes")
                return
            except Exception as exc:
                debug(f"driver write failed: {exc!r}")
        try:
            os.write(sys.__stdout__.fileno(), seq.encode())
            debug(f"emit via os.write fallback: {len(seq)} bytes")
        except Exception as exc:
            debug(f"emit_raw FAILED: {exc!r}")

    def _custom_render(self, name: str) -> str | None:
        customs = self._custom_emoji.get(self.router.active_team_id() or "", {})
        url = resolve_custom_emoji(name, customs)
        if url is None:
            return None  # not a custom emoji -> leave the :name: text
        ei = self._emoji_images
        if ei is None or not ei.enabled:
            return None  # images disabled -> render as plain :name: text
        markup = ei.markup(url)
        if markup:
            debug(f"render {name}: placeholder {markup!r}")
            return markup  # kitty image placeholder
        debug(f"render {name}: chip (image not ready)")
        return f"[reverse]:{name}:[/reverse]"  # chip until the image is ready

    def _image_render(self, url: str) -> str | None:
        mi = self._media_images
        if mi is None or not mi.enabled:
            return None
        return mi.markup(url)

    async def _prefetch_images(self) -> None:
        mi = self._media_images
        if mi is None or not mi.enabled:
            return
        urls: list[str] = []
        seen: set[str] = set()
        for m in self.query_one("#messages", MessagePane)._messages:
            for url in image_urls(getattr(m, "raw_json", "") or ""):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        changed = False
        for url in urls:
            if await mi.ensure(url):
                changed = True
        if changed:
            self._refresh_messages()

    async def _prefetch_emoji(self) -> None:
        ei = self._emoji_images
        if ei is None or not ei.enabled:
            return
        customs = self._custom_emoji.get(self.router.active_team_id() or "", {})
        if not customs:
            return
        names: set[str] = set()
        for m in self.query_one("#messages", MessagePane)._messages:
            names.update(re.findall(r":([a-zA-Z0-9_+\-]+):", m.text))
            names.update(r.emoji for r in m.reactions)  # reactions aren't in text
        custom_names = [n for n in names if resolve_custom_emoji(n, customs)]
        debug(f"prefetch: {len(names)} shortcodes, custom={custom_names}")
        changed = False
        for name in custom_names:
            url = resolve_custom_emoji(name, customs)
            img_id = await ei.ensure(url)
            debug(f"prefetch ensure {name} {url} -> id={img_id}")
            if img_id:
                changed = True
        if changed:
            debug("prefetch: re-rendering messages")
            self._refresh_messages()

    def _name_of(self, user_id: str) -> str:
        active = self.router.active_team_id() or ""
        return self._names.get(active, {}).get(user_id, user_id)

    async def _resolve_user(self, client: SlackClient, user_id: str) -> None:
        names = self._names.setdefault(client.team_id, {})
        key = (client.team_id, user_id)
        if not user_id or user_id in names or key in self._resolving:
            return
        self._resolving.add(key)
        try:
            user = await client.user_info(user_id)
        except Exception:
            user = None
        finally:
            self._resolving.discard(key)
        if user is not None:
            names[user_id] = user.name
            if client is self.client:
                self._refresh_messages()

    def _refresh_messages(self) -> None:
        # Re-render the messages already in the pane (preserving reactions and
        # other live fields the cache doesn't persist) — do NOT reload from cache.
        self.query_one("#messages", MessagePane).rerender()

    def _update_status(self) -> None:
        client = self.client
        team = client.team_name if client else ""
        name = self._channel_names.get(self.active_channel or "", "")
        seg = self._presence_segment(self.router.active_team_id() or "")
        self.query_one("#status", Static).update(f"#{name}   {team}   {seg}")

    def _presence_segment(self, team_id: str) -> str:
        presence, dnd_end = self._presence.get(team_id, ("auto", 0.0))
        if dnd_end > time.time():
            mins = int((dnd_end - time.time()) // 60) + 1
            return f"🌙 DND {mins}m"
        return "○ Away" if presence == "away" else "● Active"

    # --- input / events ---------------------------------------------------

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None or not event.item.id:
            return
        if event.item.id == THREADS_ROW_ID:
            await self._enter_threads_view()
            return
        section = self.query_one("#sidebar", Sidebar).section_for(event.item.id)
        if section is not None:
            await self._toggle_section(section)
        else:
            await self.open_channel(event.item.id)  # exits threads view if active

    async def on_thread_list_highlighted(self, event: ThreadList.Highlighted) -> None:
        o = event.overview
        if o is not None:
            await self.open_thread(o.channel_id, o.thread_ts, focus=False)

    def _name_to_id(self) -> dict[str, str]:
        team = self.router.active_team_id() or ""
        return {name: uid for uid, name in self._names.get(team, {}).items()}

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "compose":
            self._update_completion(event.input)
            if event.value:
                self._maybe_send_typing()

    def _maybe_send_typing(self) -> None:
        """Send our own user_typing for the active channel, throttled to ≥3s."""
        client = self.client
        if client is None or not self.active_channel:
            return
        if not self.config.typing_indicators:
            return
        now = time.monotonic()
        if now - self._last_typing_sent < 3.0:
            return
        self._last_typing_sent = now
        self.run_worker(client.send_typing(self.active_channel), exclusive=False)

    def _update_completion(self, inp: Input) -> None:
        value, cursor = inp.value, inp.cursor_position
        trigger, at = "", -1
        for i in range(cursor - 1, -1, -1):
            ch = value[i]
            if ch in "@:":
                if i == 0 or value[i - 1].isspace():
                    trigger, at = ch, i
                break
            if ch.isspace():
                break
        token = value[at + 1 : cursor] if at != -1 else ""
        if trigger == "@":
            options = self._mention_matches(token)
        elif trigger == ":":
            options = self._emoji_matches(token) if len(token) >= 2 else []
        else:
            options = []
        if at == -1 or not options:
            self.completion_cancel()
            return
        self._completion_at = at
        self._completion_kind = trigger
        self._completion_active = True
        popup = self.query_one("#completion-popup", MentionPopup)
        popup.set_options(options)
        popup.display = True

    def _mention_matches(self, token: str) -> list[tuple[str, str]]:
        ft = fold(token)
        cands: list[tuple[str, str]] = [
            ("@here", "@here "), ("@channel", "@channel "), ("@everyone", "@everyone "),
        ]
        names = self._names.get(self.router.active_team_id() or "", {})
        cands += [(name, f"@{name} ") for name in sorted(names.values())]
        out = []
        for label, ins in cands:
            base = label[1:] if label.startswith("@") else label
            if ft in fold(base):
                out.append((label, ins))
        return out[:8]

    def _emoji_matches(self, token: str) -> list[tuple[str, str]]:
        from slak.emoji import match
        return [(f"{glyph} :{name}:", f":{name}: ") for name, glyph in match(token)]

    def completion_move(self, delta: int) -> None:
        self.query_one("#completion-popup", MentionPopup).move(delta)

    def completion_accept(self) -> None:
        popup = self.query_one("#completion-popup", MentionPopup)
        ins = popup.current_insert()
        inp = self.query_one("#compose", Input)
        if ins is not None and self._completion_at != -1:
            value, cursor = inp.value, inp.cursor_position
            inp.value = value[: self._completion_at] + ins + value[cursor:]
            inp.cursor_position = self._completion_at + len(ins)
        self.completion_cancel()

    def completion_cancel(self) -> None:
        self._completion_active = False
        self._completion_at = -1
        self._completion_kind = ""
        self.query_one("#completion-popup", MentionPopup).display = False

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self._run_search(event.value)
            return
        if not event.value.strip():
            return
        client = self.client
        if client is None:
            return
        if event.input.id == "compose" and self.active_channel:
            text = translate_mentions(event.value, self._name_to_id())
            event.input.value = ""
            await client.post_message(self.active_channel, text)
        elif event.input.id == "thread-compose" and self.open_thread_ts:
            text = translate_mentions(event.value, self._name_to_id())
            event.input.value = ""
            await client.post_message(
                self.open_thread_channel, text, thread_ts=self.open_thread_ts
            )

    async def _consume_events(self, client: SlackClient) -> None:
        while True:
            event = await client.next_event()
            if isinstance(event, NewMessage):
                persist_messages(
                    self.cache, client.team_id, event.channel_id, [event.message]
                )
                self._maybe_notify(client, event)
                msg = event.message
                if msg.thread_ts and msg.thread_ts != msg.ts:
                    if (
                        client is self.client
                        and event.channel_id == self.open_thread_channel
                        and msg.thread_ts == self.open_thread_ts
                    ):
                        self.query_one("#thread", ThreadPanel).add_reply(
                            msg, self._name_of
                        )
                    continue  # thread replies don't touch the main pane
                is_active_view = (
                    client is self.client and event.channel_id == self.active_channel
                )
                if is_active_view:
                    # active-channel suppression: reading it, so it stays read
                    self.query_one("#messages", MessagePane).add_message(
                        event.message, self._name_of
                    )
                    if msg.user_id not in self._names.get(client.team_id, {}):
                        self.run_worker(
                            self._resolve_user(client, msg.user_id), exclusive=False
                        )
                else:
                    self.cache.update_read_state(event.channel_id, "", has_unread=True)
                    if client is self.client:
                        self._refresh_sidebar_unread()
                    self._refresh_rail()
            elif isinstance(event, ReactionUpdated) and client is self.client:
                self.query_one("#messages", MessagePane).apply_reaction(
                    event.ts, event.emoji, event.user_id, event.added
                )
                try:
                    self.query_one("#thread-messages", MessagePane).apply_reaction(
                        event.ts, event.emoji, event.user_id, event.added
                    )
                except Exception:
                    pass
                if event.added:  # a new custom reaction emoji may need its image
                    self.run_worker(self._prefetch_emoji(), exclusive=False)
            elif isinstance(event, MessageEdited):
                self.cache.edit_message(event.channel_id, event.ts, event.text)
                if client is self.client:
                    for pane_id in ("#messages", "#thread-messages"):
                        try:
                            self.query_one(pane_id, MessagePane).update_text(
                                event.ts, event.text
                            )
                        except Exception:
                            pass
            elif isinstance(event, MessageDeleted):
                self.cache.delete_message(event.channel_id, event.ts)
                if client is self.client:
                    for pane_id in ("#messages", "#thread-messages"):
                        try:
                            self.query_one(pane_id, MessagePane).remove_message(
                                event.ts
                            )
                        except Exception:
                            pass
            elif isinstance(event, SectionsChanged):
                self.run_worker(self._reload_sections(client), exclusive=False)
            elif isinstance(event, StarsChanged):
                self.run_worker(self._reload_stars(client), exclusive=False)
            elif isinstance(event, Typing):
                self._on_typing(client, event)
            elif isinstance(event, PresenceChanged):
                _, end = self._presence.get(client.team_id, ("auto", 0.0))
                self._presence[client.team_id] = (event.presence, end)
                if client is self.client:
                    self._update_status()
            elif isinstance(event, DndChanged):
                presence, _ = self._presence.get(client.team_id, ("auto", 0.0))
                self._presence[client.team_id] = (
                    presence, event.end_ts if event.enabled else 0.0
                )
                if client is self.client:
                    self._update_status()
            elif isinstance(event, Connected):
                if client is self.client:
                    self._update_status()
                self.run_worker(self._maybe_backfill(client), exclusive=False)

    def on_unmount(self) -> None:
        """Clean shutdown: checkpoint and close the cache."""
        self.cache.close()

    async def _run_realtime(self, client: SlackClient) -> None:
        try:
            await client.start_realtime()  # type: ignore[attr-defined]
        except Exception as exc:  # best-effort
            self.log(f"realtime stopped for {client.team_id}: {exc!r}")

    # --- embedded MCP server (spec 06 §4) ---------------------------------

    def mcp_snapshot(self) -> dict:
        """Build the read-only context snapshot for ``slak_get_context``."""
        client = self.client
        workspace = client.team_name if client else ""
        channel = None
        if self.active_channel and client is not None:
            name, ctype = self._chan_meta.get(client.team_id, {}).get(
                self.active_channel,
                (self._channel_names.get(self.active_channel, self.active_channel),
                 "channel"),
            )
            channel = {"id": self.active_channel, "name": name, "type": ctype}
        pane = self.query_one("#messages", MessagePane)
        sm = pane.selected_message()
        selected = message_dict(sm, self._name_of) if sm else None
        recent = [message_dict(m, self._name_of) for m in pane._messages[-20:]]
        thread = {"open": False}
        if self.open_thread_ts and self.query_one("#thread", ThreadPanel).display:
            replies = self.query_one("#thread-messages", MessagePane)._messages
            if replies:
                thread = {
                    "open": True,
                    "parent": message_dict(replies[0], self._name_of),
                    "replies": [message_dict(m, self._name_of) for m in replies[1:]],
                }
        return build_snapshot(
            workspace=workspace, channel=channel, selected=selected,
            thread=thread, recent=recent,
        )

    def mcp_set_draft(self, text: str) -> dict:
        """Populate the active composer (thread if open, else channel)."""
        if self.open_thread_ts and self.query_one("#thread", ThreadPanel).display:
            self.query_one("#thread-compose", Input).value = text
            return {"target": "thread", "channel": self.open_thread_channel, "ok": True}
        if self.active_channel:
            self.query_one("#compose", Input).value = text
            return {"target": "channel", "channel": self.active_channel, "ok": True}
        return {"ok": False}

    async def _serve_mcp(self) -> None:
        path = self.config.mcp_socket_path or default_socket_path()
        try:
            await serve_mcp(path, self.mcp_snapshot, self.mcp_set_draft)
        except Exception as exc:  # best-effort; never crash the TUI
            self.log(f"mcp server stopped: {exc!r}")

    async def _maybe_backfill(self, client: SlackClient) -> None:
        """Backfill on (re)connect, deduped to once per workspace per 30 s."""
        now = time.monotonic()
        if now - self._last_backfill.get(client.team_id, 0.0) < 30.0:
            return
        self._last_backfill[client.team_id] = now
        await self._backfill_now(client)

    async def _backfill_now(self, client: SlackClient) -> None:
        debug(f"[backfill] start {client.team_id}")
        fetched = await backfill(client, self.cache, client.team_id)
        await self._load_thread_subscriptions(client)
        if client is self.client:
            if self._view == "threads":
                team = self.router.active_team_id() or ""
                self.query_one("#threads", ThreadList).set_threads(
                    self.cache.threads_overview(team), self._name_of
                )
            elif self.active_channel:
                # re-fetch live (reactions intact) and reconcile the open channel
                await self._sync_channel(client, self.active_channel)
        debug(f"[backfill] done {client.team_id}: {fetched} msgs")

    # --- actions (also exposed via the command palette) -------------------

    def action_focus_compose(self) -> None:
        if self._view == "threads":
            # Esc in the threads view returns focus to the sidebar (spec 03 §8)
            self.query_one("#sidebar", Sidebar).focus()
            return
        self.query_one("#search", SearchBar).display = False
        self.query_one("#messages", MessagePane).remove_class("-searching")
        self.query_one("#compose", Input).focus()

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpModal):
            self.push_screen(HelpModal())

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.display = not sidebar.display

    def action_find_channel(self) -> None:
        self.run_worker(self._find_channel_flow(), exclusive=False)

    async def _find_channel_flow(self) -> None:
        client = self.client
        if client is None:
            return
        channels = await client.list_channels()
        channel_id = await self.push_screen_wait(ChannelFinder(channels))
        if channel_id:
            await self.open_channel(channel_id)

    def action_search(self) -> None:
        if self.active_channel is None:
            return
        bar = self.query_one("#search", SearchBar)
        bar.value = ""
        bar.display = True
        self._search_matches = []
        self.query_one("#messages", MessagePane).add_class("-searching")
        bar.focus()

    def _run_search(self, query: str) -> None:
        if self.active_channel is None:
            return
        self._search_matches = self.cache.search_messages(self.active_channel, query)
        self._search_idx = 0
        self._jump_to_match()

    def _jump_to_match(self) -> None:
        if self._search_matches:
            self.query_one("#messages", MessagePane).select_by_ts(
                self._search_matches[self._search_idx]
            )

    def action_search_workspace(self) -> None:
        self.run_worker(self._workspace_search_flow(), exclusive=False)

    async def _workspace_search_flow(self) -> None:
        client = self.client
        if client is None:
            return
        result = await self.push_screen_wait(SearchResultsModal(client.search))
        if result:
            channel_id, ts = result
            await self.open_channel(channel_id)
            self.query_one("#messages", MessagePane).select_by_ts(ts)

    def search_next(self) -> None:
        if self._search_matches:
            self._search_idx = min(len(self._search_matches) - 1, self._search_idx + 1)
            self._jump_to_match()

    def search_prev(self) -> None:
        if self._search_matches:
            self._search_idx = max(0, self._search_idx - 1)
            self._jump_to_match()

    def action_copy_message(self) -> None:
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg and msg.text:
            self.copy_to_clipboard(msg.text)
            self.notify("Copied message text")

    def action_scroll_latest(self) -> None:
        pane = self.query_one("#messages", MessagePane)
        pane.focus()
        pane.select_last()

    def action_scroll_oldest(self) -> None:
        pane = self.query_one("#messages", MessagePane)
        pane.focus()
        pane.select_first()

    async def action_open_thread(self) -> None:
        if self._view == "threads":
            # in the threads view Enter moves focus into the reply box
            self.query_one("#thread-compose", Input).focus()
            return
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg is None or self.active_channel is None:
            return
        await self.open_thread(self.active_channel, msg.thread_ts or msg.ts)

    async def open_thread(
        self, channel_id: str, thread_ts: str, focus: bool = True
    ) -> None:
        client = self.client
        if client is None:
            return
        try:
            replies = await client.thread_replies(channel_id, thread_ts)
        except Exception as exc:
            self.log(f"thread load failed: {exc!r}")
            return
        self.open_thread_channel = channel_id
        self.open_thread_ts = thread_ts
        panel = self.query_one("#thread", ThreadPanel)
        panel.set_thread(replies, self._name_of)
        panel.display = True
        if focus:
            self.query_one("#thread-compose", Input).focus()

    def action_toggle_thread(self) -> None:
        panel = self.query_one("#thread", ThreadPanel)
        if panel.display:
            panel.display = False
            self.action_focus_compose()
        elif self.open_thread_ts:
            panel.display = True

    def action_close_thread(self) -> None:
        self.query_one("#thread", ThreadPanel).display = False
        self.action_focus_compose()

    def action_mark_unread(self) -> None:
        if self.active_channel is None:
            return
        pane = self.query_one("#messages", MessagePane)
        if pane.selected_message() is None:
            return
        boundary = pane.boundary_before_selected()
        self.cache.update_read_state(self.active_channel, boundary, has_unread=True)
        self._refresh_sidebar_unread()
        self._refresh_rail()
        self.notify("Marked unread")
        client = self.client
        if client is not None:
            self.run_worker(
                self._mark_remote(client, self.active_channel, boundary), exclusive=False
            )

    async def _mark_remote(self, client: SlackClient, channel: str, ts: str) -> None:
        try:
            await client.mark(channel, ts)
        except Exception as exc:
            self.log(f"mark failed: {exc!r}")

    def action_presence_active(self) -> None:
        self._set_presence("auto")

    def action_presence_away(self) -> None:
        self._set_presence("away")

    def _set_presence(self, presence: str) -> None:
        client = self.client
        if client is None:
            return
        _, end = self._presence.get(client.team_id, ("auto", 0.0))
        self._presence[client.team_id] = (presence, end)
        self._update_status()
        self.run_worker(self._presence_remote(client, presence), exclusive=False)

    async def _presence_remote(self, client: SlackClient, presence: str) -> None:
        try:
            await client.set_presence(presence)
        except Exception as exc:
            self.log(f"set presence failed: {exc!r}")

    def action_snooze(self, minutes: int) -> None:
        client = self.client
        if client is None:
            return
        presence, _ = self._presence.get(client.team_id, ("auto", 0.0))
        self._presence[client.team_id] = (presence, time.time() + minutes * 60)
        self._update_status()
        self.notify(f"Do Not Disturb for {minutes} min")
        self.run_worker(self._snooze_remote(client, minutes), exclusive=False)

    async def _snooze_remote(self, client: SlackClient, minutes: int) -> None:
        try:
            await client.set_snooze(minutes)
        except Exception as exc:
            self.log(f"snooze failed: {exc!r}")

    def action_end_dnd(self) -> None:
        client = self.client
        if client is None:
            return
        presence, _ = self._presence.get(client.team_id, ("auto", 0.0))
        self._presence[client.team_id] = (presence, 0.0)
        self._update_status()
        self.run_worker(self._end_dnd_remote(client), exclusive=False)

    async def _end_dnd_remote(self, client: SlackClient) -> None:
        try:
            await client.end_dnd()
        except Exception as exc:
            self.log(f"end dnd failed: {exc!r}")

    def action_react(self) -> None:
        self.run_worker(self._react_flow(), exclusive=False)

    async def _react_flow(self) -> None:
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg is None or self.active_channel is None or self.client is None:
            return
        emoji = await self.push_screen_wait(ReactionModal())
        if emoji:
            await self._add_reaction(self.active_channel, msg.ts, emoji)

    async def _add_reaction(self, channel: str, ts: str, emoji: str) -> None:
        client = self.client
        if client is None:
            return
        try:
            await client.add_reaction(channel, ts, emoji)
        except Exception as exc:
            # surface the failure (e.g. invalid_name) instead of swallowing it
            self.notify(f"Reaction failed: {exc}", severity="error")

    def action_open_links(self) -> None:
        self.run_worker(self._open_links_flow(), exclusive=False)

    async def _open_links_flow(self) -> None:
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg is None:
            return
        links = extract_links(msg.text)
        if not links:
            self.notify("No links in the selected message")
            return
        if len(links) == 1:
            self._open_url(links[0])
            return
        url = await self.push_screen_wait(LinkPicker(links))
        if url:
            self._open_url(url)

    def action_edit_message(self) -> None:
        self.run_worker(self._edit_flow(), exclusive=False)

    async def _edit_flow(self) -> None:
        client = self.client
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg is None or self.active_channel is None or client is None:
            return
        if msg.user_id != client.self_user_id:
            self.notify("You can only edit your own messages")
            return
        new_text = await self.push_screen_wait(EditModal(msg.text))
        if new_text and new_text != msg.text:
            try:
                await client.update_message(self.active_channel, msg.ts, new_text)
            except Exception as exc:
                self.notify(f"Edit failed: {exc}", severity="error")

    def action_delete_message(self) -> None:
        self.run_worker(self._delete_flow(), exclusive=False)

    async def _delete_flow(self) -> None:
        client = self.client
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg is None or self.active_channel is None or client is None:
            return
        if msg.user_id != client.self_user_id:
            self.notify("You can only delete your own messages")
            return
        try:
            await client.delete_message(self.active_channel, msg.ts)
        except Exception as exc:
            self.notify(f"Delete failed: {exc}", severity="error")


def _top_level(messages):
    """Keep only channel-level messages (drop thread replies)."""
    return [m for m in messages if not m.thread_ts or m.thread_ts == m.ts]


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()
