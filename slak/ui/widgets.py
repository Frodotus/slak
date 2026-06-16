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

"""Textual widgets for the slak shell.

These are deliberately thin: they render state handed to them and emit messages.
The App owns data flow and Slack/cache interaction.
"""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, ListItem, ListView, OptionList, Static

from textual.screen import ModalScreen

from rich.markup import escape

from slak.emoji import emoji_glyph
from slak.finder import rank_channels
from slak.help import render_help
from slak.render import render_message
from slak.slack import Reaction, RemoteChannel, RemoteMessage


def _mutate_reaction(m: RemoteMessage, emoji: str, user_id: str, added: bool) -> None:
    """Apply a reaction add/remove to a message in place."""
    for r in list(m.reactions):
        if r.emoji == emoji:
            if added and user_id not in r.users:
                r.users.append(user_id)
                r.count += 1
            elif not added and user_id in r.users:
                r.users.remove(user_id)
                r.count -= 1
                if r.count <= 0:
                    m.reactions.remove(r)
            return
    if added:
        m.reactions.append(Reaction(emoji=emoji, count=1, users=[user_id]))


def _fmt_time(ts: str) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(ts)))
    except (ValueError, OverflowError):
        return ""


class Rail(Static):
    """Workspace rail — stacked workspace initials with unread dots."""

    def set_workspaces(
        self,
        initials: list[str],
        active: int = 0,
        unread: list[bool] | None = None,
    ) -> None:
        unread = unread or []
        lines = []
        for i, ini in enumerate(initials):
            dot = " [b]●[/]" if i < len(unread) and unread[i] else ""
            label = f"[b]{ini}[/]" if i == active else ini
            lines.append(f"{label}{dot}")
        self.update("\n\n".join(lines))


def _channel_glyph(ch: RemoteChannel) -> str:
    return {"dm": "●", "group_dm": "●", "private": "◆"}.get(ch.type, "#")


class Sidebar(ListView):
    """Channel list. Item ids are channel ids; unread channels are bold + dotted."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._channels: list[RemoteChannel] = []
        self._unread: set[str] = set()

    def set_channels(self, channels: list[RemoteChannel]) -> None:
        self._channels = channels
        self.clear()
        for ch in channels:
            self.append(ListItem(Static(self._label(ch)), id=ch.id))

    def set_unread(self, unread_ids: set[str]) -> None:
        self._unread = set(unread_ids)
        # update mounted labels; freshly-appended items repaint via _label on mount
        for ch in self._channels:
            try:
                item = self.get_child_by_id(ch.id, ListItem)
                item.query_one(Static).update(self._label(ch))
            except Exception:
                continue

    def unread_ids(self) -> set[str]:
        return set(self._unread)

    def _label(self, ch: RemoteChannel) -> str:
        glyph = _channel_glyph(ch)
        if ch.id in self._unread:
            return f"[b]{glyph} {ch.name}  ●[/]"
        return f"{glyph} {ch.name}"


class MessagePane(VerticalScroll, can_focus=True):
    """Scrollable, selectable list of messages for the active channel.

    Selection is only meaningful (and only highlighted) when the pane has focus;
    the compose box is the home focus. ``↑``/``↓`` move the selection.
    """

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._messages: list[RemoteMessage] = []
        self._widgets: list[Static] = []
        self._selected: int = -1
        self._name_of = str
        self._custom_render = None

    def set_custom_render(self, fn) -> None:
        self._custom_render = fn

    def set_messages(self, messages: list[RemoteMessage], name_of=str) -> None:
        self.remove_children()
        self._name_of = name_of
        self._messages = list(messages)
        self._widgets = [Static(self._body(m), classes="message") for m in messages]
        for w in self._widgets:
            self.mount(w)
        self._selected = len(self._messages) - 1
        self._apply_selection()
        self.scroll_end(animate=False)

    def add_message(self, m: RemoteMessage, name_of=str) -> None:
        self._name_of = name_of
        follow = self._selected == len(self._messages) - 1
        w = Static(self._body(m), classes="message")
        self._messages.append(m)
        self._widgets.append(w)
        self.mount(w)
        if follow:
            self._selected = len(self._messages) - 1
        self._apply_selection()
        self.scroll_end(animate=False)

    def rerender(self) -> None:
        """Re-render current messages in place (e.g. after an emoji image loads
        or a username resolves). Updates each widget's content from the messages
        already held — never reloads from cache — so reactions and other live
        fields are preserved, and there's no remove/remount churn."""
        for widget, msg in zip(self._widgets, self._messages):
            widget.update(self._body(msg))

    def apply_reaction(self, ts: str, emoji: str, user_id: str, added: bool) -> None:
        for i, m in enumerate(self._messages):
            if m.ts == ts:
                _mutate_reaction(m, emoji, user_id, added)
                self._widgets[i].update(self._body(m))
                return

    def selected_message(self) -> RemoteMessage | None:
        if 0 <= self._selected < len(self._messages):
            return self._messages[self._selected]
        return None

    def boundary_before_selected(self) -> str:
        """ts of the message just before the selection (or '0' at the top).

        Marking unread from the selected message sets the read pointer here.
        """
        if self._selected <= 0:
            return "0"
        return self._messages[self._selected - 1].ts

    def select_by_ts(self, ts: str) -> bool:
        for i, m in enumerate(self._messages):
            if m.ts == ts:
                self._selected = i
                self._apply_selection()
                self.scroll_to_widget(self._widgets[i], animate=False)
                return True
        return False

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_cursor_down(self) -> None:
        self._move(1)

    def select_first(self) -> None:
        self._move(-len(self._messages))

    def select_last(self) -> None:
        self._move(len(self._messages))

    def _move(self, delta: int) -> None:
        if not self._messages:
            return
        self._selected = max(0, min(len(self._messages) - 1, self._selected + delta))
        self._apply_selection()
        self.scroll_to_widget(self._widgets[self._selected], animate=False)

    def _apply_selection(self) -> None:
        for i, w in enumerate(self._widgets):
            w.set_class(i == self._selected, "-selected")

    def _body(self, m: RemoteMessage) -> str:
        author = escape(self._name_of(m.user_id))
        text = render_message(m.text, self._name_of, self._custom_render)
        body = f"[b]{author}[/]  [dim]{_fmt_time(m.ts)}[/]\n{text}"
        if m.reactions:
            # dim only the count — the emoji's own markup (esp. a kitty image
            # placeholder, whose fg colour encodes the image id) must be untouched
            pills = "  ".join(
                f"{self._reaction_emoji(r.emoji)} [dim]{r.count}[/dim]"
                for r in m.reactions
            )
            body += f"\n{pills}"
        return body

    def _reaction_emoji(self, name: str) -> str:
        if self._custom_render:
            markup = self._custom_render(name)
            if markup:  # custom emoji: image placeholder or chip
                return markup
        return emoji_glyph(name)  # standard glyph or :name: fallback


class ThreadPanel(Vertical):
    """Right-side thread view: parent + replies + a reply box.

    Reuses MessagePane for the replies list so rendering stays consistent.
    Hidden until a thread is opened.
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="thread-header")
        yield MessagePane(id="thread-messages")
        yield Input(placeholder="Reply…", id="thread-compose")

    def set_thread(self, replies: list[RemoteMessage], name_of=str) -> None:
        count = max(0, len(replies) - 1)
        plural = "reply" if count == 1 else "replies"
        self.query_one("#thread-header", Static).update(f"Thread · {count} {plural}")
        self.query_one("#thread-messages", MessagePane).set_messages(replies, name_of)

    def add_reply(self, m: RemoteMessage, name_of=str) -> None:
        self.query_one("#thread-messages", MessagePane).add_message(m, name_of)


class ReactionModal(ModalScreen[str]):
    """Minimal emoji-name input. Dismisses with the typed shortcode (or '')."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="emoji name (e.g. tada, +1)", id="reaction-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class SearchBar(Input):
    """In-channel search input. Up/Down step through matches (older/newer)."""

    BINDINGS = [
        Binding("down", "next_match", show=False),
        Binding("up", "prev_match", show=False),
    ]

    def action_next_match(self) -> None:
        self.app.search_next()

    def action_prev_match(self) -> None:
        self.app.search_prev()


class MentionPopup(OptionList):
    """Dropdown of @mention candidates shown above the compose box."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._inserts: list[str] = []

    def set_options(self, options: list[tuple[str, str]]) -> None:
        self._inserts = [ins for _, ins in options]
        self.clear_options()
        for label, _ in options:
            self.add_option(label)
        if options:
            self.highlighted = 0

    def move(self, delta: int) -> None:
        if self.option_count:
            cur = self.highlighted or 0
            self.highlighted = max(0, min(self.option_count - 1, cur + delta))

    def current_insert(self) -> str | None:
        if self.highlighted is not None and 0 <= self.highlighted < len(self._inserts):
            return self._inserts[self.highlighted]
        return None


class ComposeInput(Input):
    """Compose box that defers nav keys to the completion popup while it's open."""

    def on_key(self, event) -> None:
        app = self.app
        if not getattr(app, "_completion_active", False):
            return
        if event.key == "down":
            app.completion_move(1)
        elif event.key == "up":
            app.completion_move(-1)
        elif event.key in ("enter", "tab"):
            app.completion_accept()
        elif event.key == "escape":
            app.completion_cancel()
        else:
            return
        event.stop()
        event.prevent_default()


class SearchResultsModal(ModalScreen):
    """Workspace search: a query input over a results list. Dismisses with the
    chosen (channel_id, ts), or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, run_search):
        super().__init__()
        self._run_search = run_search  # async (query) -> list[SearchResult]
        self._results: list = []

    def compose(self) -> ComposeResult:
        with Vertical(id="ws-search"):
            yield Input(placeholder="Search all channels…", id="ws-search-input")
            yield OptionList(id="ws-search-results")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ws-search-input":
            self.run_worker(self._do(event.value), exclusive=True)

    async def _do(self, query: str) -> None:
        results = await self._run_search(query)
        self._results = results
        opts = self.query_one("#ws-search-results", OptionList)
        opts.clear_options()
        for r in results:
            opts.add_option(f"#{r.channel_name}  {r.text[:60]}")
        if results:
            opts.highlighted = 0
            opts.focus()

    def on_option_list_option_selected(self, event) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._results):
            r = self._results[idx]
            self.dismiss((r.channel_id, r.ts))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChannelFinder(ModalScreen):
    """Fuzzy channel/DM finder (``Ctrl+K``, spec 03 §5).

    Type to filter (accent-insensitive, match-tier order); ``↑``/``↓`` move the
    highlight while the input keeps focus; ``Enter`` opens the highlighted
    channel; ``Esc`` cancels. Dismisses with the chosen channel id, or ``None``.
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("up", "cursor_up", show=False),
    ]

    def __init__(self, channels: list[RemoteChannel]):
        super().__init__()
        self._all = list(channels)  # incoming order = recency order
        self._shown: list[RemoteChannel] = list(channels)

    def compose(self) -> ComposeResult:
        with Vertical(id="finder"):
            yield Input(placeholder="Jump to channel…", id="finder-input")
            yield OptionList(id="finder-results")

    def on_mount(self) -> None:
        self._populate("")
        self.query_one("#finder-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(event.value)

    def _populate(self, query: str) -> None:
        self._shown = rank_channels(self._all, query)
        opts = self.query_one("#finder-results", OptionList)
        opts.clear_options()
        for ch in self._shown:
            opts.add_option(f"{_channel_glyph(ch)} {ch.name}")
        if self._shown:
            opts.highlighted = 0

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        opts = self.query_one("#finder-results", OptionList)
        if opts.option_count:
            cur = opts.highlighted or 0
            opts.highlighted = max(0, min(opts.option_count - 1, cur + delta))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._accept()

    def on_option_list_option_selected(self, event) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._shown):
            self.dismiss(self._shown[idx].id)

    def _accept(self) -> None:
        opts = self.query_one("#finder-results", OptionList)
        idx = opts.highlighted
        if idx is not None and 0 <= idx < len(self._shown):
            self.dismiss(self._shown[idx].id)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpModal(ModalScreen):
    """Keyboard-shortcut help (``F1``, overview §10/§11).

    A scrollable panel of the keybinding table with a version/attribution
    footer. ``F1`` or ``Esc`` closes it."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("f1", "close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help"):
            yield Static(render_help(), id="help-body")

    def action_close(self) -> None:
        self.dismiss(None)
