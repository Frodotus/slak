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
from types import SimpleNamespace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Input, ListItem, ListView, OptionList, Static

from textual.screen import ModalScreen

from rich.markup import escape

from slak.blockkit import render_extras
from slak.emoji import emoji_glyph
from slak.finder import rank_by_name
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
    # private uses the Nerd Font padlock (U+F023): a single-width lock, matching
    # slk. Needs a Nerd Font installed (as slk assumes).
    return {"dm": "●", "group_dm": "●", "private": ""}.get(ch.type, "#")


# Synthetic sidebar row that opens the threads view (spec 03 §8).
THREADS_ROW_ID = "threads-landmark"
# Prefix for collapsible section-header rows (spec 03 §9).
SECTION_PREFIX = "sec-"


class Sidebar(ListView):
    """Channel list. Item ids are channel ids; unread channels are bold + dotted.

    A synthetic ``⚑ Threads`` landmark row sits at the top (id
    :data:`THREADS_ROW_ID`); selecting it opens the threads view.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._channels: list[RemoteChannel] = []
        self._unread: set[str] = set()
        self._section_ids: dict[str, str] = {}  # item id -> section name

    async def set_channels(self, channels: list[RemoteChannel]) -> None:
        self._channels = channels
        self._section_ids = {}
        await self.clear()  # await: removal is deferred, must finish before re-adding
        self.append(ListItem(Static("⚑ Threads"), id=THREADS_ROW_ID))
        for ch in channels:
            self.append(ListItem(Static(self._label(ch)), id=ch.id))

    async def set_sections(self, groups, collapsed: set[str]) -> None:
        """Render channels grouped under collapsible section headers (spec 03 §9).

        ``groups`` is ``[(section_name | None, [channels])]``; a collapsed
        section shows only its header. Header rows carry ids ``sec-<n>`` mapped
        back to names via :meth:`section_for`.
        """
        self._channels = [c for _, chans in groups for c in chans]
        self._section_ids = {}
        await self.clear()
        self.append(ListItem(Static("⚑ Threads"), id=THREADS_ROW_ID))
        for i, (name, chans) in enumerate(groups):
            if name is not None:
                item_id = f"{SECTION_PREFIX}{i}"
                self._section_ids[item_id] = name
                arrow = "▸" if name in collapsed else "▾"
                self.append(
                    ListItem(
                        Static(f"[b]{arrow} {name}[/]"),
                        id=item_id, classes="section-header",
                    )
                )
                if name in collapsed:
                    continue
            for ch in chans:
                self.append(ListItem(Static(self._label(ch)), id=ch.id))

    def section_for(self, item_id: str) -> str | None:
        return self._section_ids.get(item_id)

    def add_channel(self, ch: RemoteChannel) -> None:
        """Append one channel (e.g. a freshly-opened DM) if not already listed."""
        if any(c.id == ch.id for c in self._channels):
            return
        self._channels.append(ch)
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
        self._image_render = None

    def set_custom_render(self, fn) -> None:
        self._custom_render = fn

    def set_image_render(self, fn) -> None:
        self._image_render = fn

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

    def update_text(self, ts: str, text: str) -> None:
        """Replace a message's body text in place (after an edit)."""
        for i, m in enumerate(self._messages):
            if m.ts == ts:
                m.text = text
                self._widgets[i].update(self._body(m))
                return

    def remove_message(self, ts: str) -> None:
        """Drop a deleted message and keep the selection valid."""
        for i, m in enumerate(self._messages):
            if m.ts == ts:
                self._widgets[i].remove()
                del self._messages[i]
                del self._widgets[i]
                self._selected = min(self._selected, len(self._messages) - 1)
                self._apply_selection()
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
        extras = (
            render_extras(m.raw_json, self._name_of, self._custom_render,
                          self._image_render)
            if getattr(m, "raw_json", "")
            else []
        )
        if extras:
            body += "\n" + "\n".join(extras)
        if getattr(m, "reply_count", 0):
            n = m.reply_count
            body += f"\n[$accent]💬 {n} repl{'y' if n == 1 else 'ies'}[/]"
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


class ThreadList(VerticalScroll, can_focus=True):
    """Scrollable list of subscribed threads — the threads view (spec 03 §8).

    The highlight follows the cursor and posts :class:`Highlighted` so the app
    can show that thread's replies in the side panel.
    """

    class Highlighted(Message):
        def __init__(self, overview) -> None:
            self.overview = overview
            super().__init__()

    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rows: list = []
        self._widgets: list[Static] = []
        self._selected: int = -1
        self._name_of = str
        self._custom_render = None

    def set_custom_render(self, fn) -> None:
        self._custom_render = fn

    def set_threads(self, overviews, name_of=str) -> None:
        self.remove_children()
        self._rows = list(overviews)
        self._name_of = name_of
        self._widgets = [Static(self._body(o), classes="thread-row") for o in self._rows]
        for w in self._widgets:
            self.mount(w)
        self._selected = 0 if self._rows else -1
        self._apply_selection()
        if self._rows:
            self.post_message(self.Highlighted(self._rows[0]))

    def selected_overview(self):
        if 0 <= self._selected < len(self._rows):
            return self._rows[self._selected]
        return None

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_cursor_down(self) -> None:
        self._move(1)

    def _move(self, delta: int) -> None:
        if not self._rows:
            return
        self._selected = max(0, min(len(self._rows) - 1, self._selected + delta))
        self._apply_selection()
        self.scroll_to_widget(self._widgets[self._selected], animate=False)
        self.post_message(self.Highlighted(self._rows[self._selected]))

    def _apply_selection(self) -> None:
        for i, w in enumerate(self._widgets):
            w.set_class(i == self._selected, "-selected")

    def _body(self, o) -> str:
        author = escape(self._name_of(o.parent_user_id)) if o.parent_user_id else "—"
        dot = " [b]●[/]" if o.unread else ""
        header = f"[b]#{escape(o.channel_name)}[/]  ·  {author}{dot}"
        src = o.parent_text or "(parent not loaded)"
        preview = render_message(src[:120], self._name_of, self._custom_render)
        word = "reply" if o.reply_count == 1 else "replies"
        last = self._name_of(o.last_reply_user_id) if o.last_reply_user_id else "—"
        meta = f"[dim]{o.reply_count} {word} · last by {escape(last)}[/dim]"
        return f"{header}\n  [dim]>[/dim] {preview}\n  {meta}"


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


class EditModal(ModalScreen[str]):
    """Edit-message input, prefilled with the current text (``Ctrl+E``, spec 04).

    Dismisses with the edited text, or ``''`` on cancel."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, text: str):
        super().__init__()
        self._initial = text

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-box"):
            yield Static("Edit message", id="edit-title")
            yield Input(value=self._initial, id="edit-input")

    def on_mount(self) -> None:
        self.query_one("#edit-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

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


class FuzzyPicker(ModalScreen):
    """Reusable fuzzy-filter overlay (channel finder, workspace switcher).

    Type to filter (accent-insensitive, match-tier order, via
    :func:`slak.finder.rank_by_name`); ``↑``/``↓`` move the highlight while the
    input keeps focus; ``Enter`` accepts the highlighted item; ``Esc`` cancels.
    Dismisses with the chosen item's ``.id``, or ``None``.

    Subclasses set :attr:`PREFIX` (CSS id stem) and :attr:`PLACEHOLDER`, and may
    override :meth:`_label` to format each row.
    """

    PREFIX = "picker"
    PLACEHOLDER = "Filter…"

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("up", "cursor_up", show=False),
    ]

    def __init__(self, items):
        super().__init__()
        self._all = list(items)  # incoming order = recency order
        self._shown = list(items)

    def compose(self) -> ComposeResult:
        with Vertical(id=self.PREFIX):
            yield Input(placeholder=self.PLACEHOLDER, id=f"{self.PREFIX}-input")
            yield OptionList(id=f"{self.PREFIX}-results")

    def on_mount(self) -> None:
        self._populate("")
        self.query_one(f"#{self.PREFIX}-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(event.value)

    def _label(self, item) -> str:
        return item.name

    def _results(self) -> OptionList:
        return self.query_one(f"#{self.PREFIX}-results", OptionList)

    def _populate(self, query: str) -> None:
        self._shown = rank_by_name(self._all, query)
        opts = self._results()
        opts.clear_options()
        for item in self._shown:
            opts.add_option(self._label(item))
        if self._shown:
            opts.highlighted = 0

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        opts = self._results()
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
        idx = self._results().highlighted
        if idx is not None and 0 <= idx < len(self._shown):
            self.dismiss(self._shown[idx].id)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChannelFinder(FuzzyPicker):
    """Fuzzy channel/DM finder (``Ctrl+K``, spec 03 §5)."""

    PREFIX = "finder"
    PLACEHOLDER = "Jump to channel…"

    def _label(self, item: RemoteChannel) -> str:
        return f"{_channel_glyph(item)} {item.name}"


class WorkspaceSwitcher(FuzzyPicker):
    """Fuzzy workspace switcher (``Ctrl+W``, spec 03 §6).

    Items are any objects with ``.id`` (team id) and ``.name`` (workspace name).
    """

    PREFIX = "wsswitch"
    PLACEHOLDER = "Switch workspace…"


class LinkPicker(FuzzyPicker):
    """Pick a URL to open when a message has several (``Ctrl+O``, spec 04).

    Built from a list of URL strings; dismisses with the chosen URL or ``None``.
    """

    PREFIX = "linkpick"
    PLACEHOLDER = "Open link…"

    def __init__(self, urls: list[str]):
        super().__init__([SimpleNamespace(id=u, name=u) for u in urls])


class MultiUserPicker(ModalScreen):
    """New-message composer: filter users, multi-select, start a DM/MPIM
    (``Ctrl+N``, spec 04). Type to filter; ``Tab`` (or click) toggles the
    highlighted user; ``Enter`` starts the conversation; ``Esc`` cancels.

    With nothing toggled, ``Enter`` starts a DM with the highlighted user (the
    common case). Dismisses with the chosen user-id list, or ``None``.
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("tab", "toggle", show=False, priority=True),
    ]

    def __init__(self, users):
        super().__init__()
        self._all = list(users)
        self._shown = list(users)
        self._selected: list[str] = []  # ordered by toggle, for stable MPIM ids

    def compose(self) -> ComposeResult:
        with Vertical(id="newmsg"):
            yield Input(placeholder="To: name… (Tab adds, Enter starts)", id="newmsg-input")
            yield OptionList(id="newmsg-results")

    def on_mount(self) -> None:
        self._populate("")
        self.query_one("#newmsg-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(event.value)

    def _results(self) -> OptionList:
        return self.query_one("#newmsg-results", OptionList)

    def _label(self, user) -> str:
        mark = "✓" if user.id in self._selected else " "
        return f"[{mark}] {user.name}"

    def _populate(self, query: str, keep: int | None = None) -> None:
        self._shown = rank_by_name(self._all, query)
        opts = self._results()
        opts.clear_options()
        for user in self._shown:
            opts.add_option(self._label(user))
        if self._shown:
            opts.highlighted = keep if keep is not None else 0

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        opts = self._results()
        if opts.option_count:
            cur = opts.highlighted or 0
            opts.highlighted = max(0, min(opts.option_count - 1, cur + delta))

    def action_toggle(self) -> None:
        opts = self._results()
        idx = opts.highlighted
        if idx is None or not (0 <= idx < len(self._shown)):
            return
        user = self._shown[idx]
        if user.id in self._selected:
            self._selected.remove(user.id)
        else:
            self._selected.append(user.id)
        self._populate(self.query_one("#newmsg-input", Input).value, keep=idx)

    def on_option_list_option_selected(self, event) -> None:
        # Mouse click toggles, mirroring Tab.
        if 0 <= event.option_index < len(self._shown):
            self._results().highlighted = event.option_index
            self.action_toggle()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._selected:
            self.dismiss(list(self._selected))
            return
        opts = self._results()
        idx = opts.highlighted
        if idx is not None and 0 <= idx < len(self._shown):
            self.dismiss([self._shown[idx].id])
        else:
            self.dismiss([])

    def action_cancel(self) -> None:
        self.dismiss(None)


class ThemePicker(FuzzyPicker):
    """Pick a colour theme (``Ctrl+Y``, spec 05 §2).

    Built from theme names; dismisses with the chosen name or ``None``. The
    placeholder distinguishes per-workspace from default-theme selection.
    """

    PREFIX = "themepick"
    PLACEHOLDER = "Pick a theme…"

    def __init__(self, names: list[str], placeholder: str | None = None):
        super().__init__([SimpleNamespace(id=n, name=n) for n in names])
        if placeholder:
            self.PLACEHOLDER = placeholder


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
