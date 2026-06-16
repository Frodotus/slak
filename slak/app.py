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

from slak.cache import Cache, Channel
from slak.debuglog import debug
from slak.emoji import resolve_custom_emoji
from slak.images import EmojiImages, detect_protocol, tmux_passthrough
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
    persist_messages,
    to_remote_message,
    translate_mentions,
    window_title,
)
from slak.slack import (
    Connected,
    DndChanged,
    NewMessage,
    PresenceChanged,
    ReactionUpdated,
    SlackClient,
)
from slak.ui.commands import PyslkCommands
from slak.ui.widgets import (
    ChannelFinder,
    ComposeInput,
    HelpModal,
    LinkPicker,
    MentionPopup,
    MessagePane,
    Rail,
    ReactionModal,
    SearchBar,
    SearchResultsModal,
    Sidebar,
    ThreadPanel,
    WorkspaceSwitcher,
)
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
    ):
        super().__init__()
        self.router = router
        self.cache = cache
        self.config = config
        self._notifier = notifier or DesktopNotifier()
        self._open_url = url_opener or webbrowser.open
        self.active_channel: str | None = None
        self._nav: dict[str, NavHistory] = {}  # team_id -> channel back/forward
        self._channel_names: dict[str, str] = {}
        self._chan_meta: dict[str, dict[str, tuple[str, str]]] = {}  # team->cid->(name,type)
        self._names: dict[str, dict[str, str]] = {}  # team_id -> {user_id: display}
        self._custom_emoji: dict[str, dict[str, str]] = {}  # team_id -> {name: url}
        self._emoji_images: EmojiImages | None = None
        self._resolving: set[tuple[str, str]] = set()
        self.open_thread_ts: str = ""
        self.open_thread_channel: str = ""
        self._search_matches: list[str] = []
        self._search_idx: int = 0
        self._presence: dict[str, tuple[str, float]] = {}  # team -> (presence, dnd_end)
        self._completion_active: bool = False
        self._completion_at: int = -1
        self._completion_kind: str = ""  # "@" or ":"

    @property
    def client(self) -> SlackClient | None:
        return self.router.active()

    def compose(self) -> ComposeResult:
        yield Rail(id="rail")
        with Horizontal():
            yield Sidebar(id="sidebar")
            with Vertical(id="main"):
                yield Static("", id="header")
                yield Static("─" * 200, id="header-rule")
                yield MessagePane(id="messages")
                yield SearchBar(placeholder="Search this channel…", id="search")
                yield MentionPopup(id="completion-popup")
                yield ComposeInput(placeholder="Message…", id="compose")
            yield ThreadPanel(id="thread")
        yield Static("", id="status")

    async def on_mount(self) -> None:
        self._init_emoji_images()
        for pane_id in ("#messages", "#thread-messages"):
            try:
                self.query_one(pane_id, MessagePane).set_custom_render(self._custom_render)
            except Exception:
                pass
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

    async def _load_active_workspace(self) -> None:
        client = self.client
        if client is None:
            return
        await self._load_users(client)
        await self._load_custom_emoji(client)
        channels = await client.list_channels()
        self._channel_names = {ch.id: ch.name for ch in channels}
        self._upsert_channels(client.team_id, channels)
        self.query_one("#sidebar", Sidebar).set_channels(channels)
        self.active_channel = None
        if channels:
            await self.open_channel(channels[0].id)
        else:
            self.query_one("#messages", MessagePane).set_messages([], self._name_of)
        self._refresh_sidebar_unread()
        self._update_status()

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

    async def open_channel(self, channel_id: str, record_history: bool = True) -> None:
        client = self.client
        if client is None:
            return
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

    async def _load_users(self, client: SlackClient) -> None:
        try:
            users = await client.list_users()
        except Exception as exc:
            self.log(f"user list failed for {client.team_id}: {exc!r}")
            return
        self._names[client.team_id] = {u.id: u.name for u in users}

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
        debug(f"init emoji images: protocol={proto} enabled={self._emoji_images.enabled}")

    async def _fetch_image(self, url: str) -> bytes:
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
        if event.item is not None and event.item.id:
            await self.open_channel(event.item.id)

    def _name_to_id(self) -> dict[str, str]:
        team = self.router.active_team_id() or ""
        return {name: uid for uid, name in self._names.get(team, {}).items()}

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "compose":
            self._update_completion(event.input)

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
            elif isinstance(event, Connected) and client is self.client:
                self._update_status()

    def on_unmount(self) -> None:
        """Clean shutdown: checkpoint and close the cache."""
        self.cache.close()

    async def _run_realtime(self, client: SlackClient) -> None:
        try:
            await client.start_realtime()  # type: ignore[attr-defined]
        except Exception as exc:  # best-effort
            self.log(f"realtime stopped for {client.team_id}: {exc!r}")

    # --- actions (also exposed via the command palette) -------------------

    def action_focus_compose(self) -> None:
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
        msg = self.query_one("#messages", MessagePane).selected_message()
        if msg is None or self.active_channel is None:
            return
        await self.open_thread(self.active_channel, msg.thread_ts or msg.ts)

    async def open_thread(self, channel_id: str, thread_ts: str) -> None:
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
