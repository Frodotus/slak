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

import json

from textual.widgets import Input

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage, RemoteUser
from slak.ui.widgets import MessagePane, Sidebar
from slak.workspace import WorkspaceRouter


async def test_dm_channel_name_resolves_to_peer_display_name():
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("D1", "", "dm", user="U2")],
        history={"D1": [RemoteMessage("1.0", "U2", "hey")]},
        users=[RemoteUser("U2", "bob")],
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert app._channel_names["D1"] == "bob"
        assert app._sidebar_channels[0].name == "bob"


async def test_unread_channels_seeded_from_client_counts():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
        unreads=["C2"],  # has unread on Slack at launch
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        unread = app.query_one("#sidebar", Sidebar).unread_ids()
        assert "C2" in unread       # shown as unread
        assert "C1" not in unread   # the channel opened on launch is read


async def test_event_consumer_survives_a_handler_exception():
    from slak.slack import Typing

    app = make_app()  # C1 active, seeded with one message
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()

        def boom(client, event):
            raise RuntimeError("boom")

        app._on_typing = boom  # the next Typing event will blow up mid-dispatch
        await app.client.emit_event(Typing("C1", "U2"))
        await app.client.post_message("C1", "still works")  # must still be handled
        for _ in range(4):
            await pilot.pause()
        pane = app.query_one("#messages", MessagePane)
        assert len(pane.children) == 2  # seeded + "still works" (loop didn't die)


async def test_sidebar_channel_names_clip_not_wrap():
    from textual.widgets import ListItem, Static

    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "a-very-long-channel-name-that-exceeds-the-sidebar")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        item = app.query_one("#sidebar", Sidebar).get_child_by_id("C1", ListItem)
        static = item.query_one(Static)
        assert static.styles.text_wrap == "nowrap"
        assert static.styles.text_overflow == "ellipsis"


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme Corp",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
        history={"C1": [RemoteMessage("100.0", "alice", "hello world")]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_boots_with_first_channel_open():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):  # allow the cache-first sync worker to run
            await pilot.pause()
        assert app.active_channel == "C1"
        pane = app.query_one("#messages", MessagePane)
        assert len(pane.children) == 1


async def test_opening_channel_persists_history_to_cache():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        cached = app.cache.get_messages("C1")
        assert [m.text for m in cached] == ["hello world"]
        assert cached[0].workspace_id == "T1"


async def test_reopens_last_used_channel_on_restart(tmp_path):
    db = str(tmp_path / "cache.db")  # file-backed so it survives a "restart"

    def build() -> PyslkApp:
        client = FakeSlackClient(
            team_id="T1", team_name="Acme",
            channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
            history={"C2": [RemoteMessage("5.0", "u", "hi")]},
        )
        return PyslkApp(
            router=WorkspaceRouter.single(client), cache=Cache.open(db), config=Config()
        )

    first = build()
    async with first.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert first.active_channel == "C1"  # defaults to first on a fresh cache
        await first.open_channel("C2")
        for _ in range(2):
            await pilot.pause()

    second = build()  # "restart" with the same cache
    async with second.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert second.active_channel == "C2"  # restored last-used channel
        sidebar = second.query_one("#sidebar", Sidebar)
        assert sidebar.highlighted_child is not None
        assert sidebar.highlighted_child.id == "C2"  # and selected in the list


async def test_finder_discovers_and_joins_an_unjoined_public_channel():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],            # joined
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
        public_channels=[
            RemoteChannel("C1", "general", is_member=True),
            RemoteChannel("C9", "announcements", is_member=False),  # not joined
        ],
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(5):  # let the background public-channel load run
            await pilot.pause()
        assert app._public_channels.get("T1")  # loaded
        # simulate the finder returning the unjoined channel, via the join flow
        ok = await app._join_channel(client, "C9")
        await pilot.pause()
        assert ok and "C9" in client.joined            # joined server-side
        await app.open_channel("C9")
        await pilot.pause()
        assert app.active_channel == "C9"
        # it now appears in the sidebar
        assert app.query_one("#sidebar", Sidebar).get_child_by_id("C9") is not None


async def test_rail_hidden_with_single_workspace():
    app = make_app()  # one workspace
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert app.query_one("#rail").display is False  # no rail column wasted


async def test_rail_shown_with_multiple_workspaces():
    app = make_multi_app()  # T1, T2
    async with app.run_test() as pilot:
        for _ in range(5):
            await pilot.pause()
        assert app.query_one("#rail").display is True


async def test_switching_workspace_remembers_it_for_next_launch(tmp_path):
    cfg_path = tmp_path / "config.toml"
    a = FakeSlackClient("T1", "Acme", channels=[RemoteChannel("C1", "general")],
                        history={"C1": [RemoteMessage("1.0", "u", "hi")]})
    b = FakeSlackClient("T2", "Beta", channels=[RemoteChannel("C9", "beta")],
                        history={"C9": [RemoteMessage("1.0", "u", "hi")]})
    app = PyslkApp(router=WorkspaceRouter([a, b], order=["T1", "T2"]),
                   cache=Cache.open(":memory:"), config=Config(), config_path=cfg_path)
    async with app.run_test() as pilot:
        for _ in range(5):
            await pilot.pause()
        assert app.config.last_workspace == "T1"   # initial active recorded
        await app.action_switch_workspace(1)       # -> T2
        for _ in range(4):
            await pilot.pause()
        assert app.config.last_workspace == "T2"
        assert "T2" in cfg_path.read_text()         # persisted to disk


async def test_panel_widths_restored_from_config_and_resize_persists(tmp_path):
    from slak.ui.widgets import Splitter
    cfg_path = tmp_path / "config.toml"
    cfg = Config(); cfg.sidebar_width = 34
    client = FakeSlackClient("T1", "Acme", channels=[RemoteChannel("C1", "general")],
                             history={"C1": [RemoteMessage("1.0", "u", "hi")]})
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"),
                   config=cfg, config_path=cfg_path)
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        # configured sidebar width applied on mount
        assert app.query_one("#sidebar").styles.width.cells == 34
        # a splitter resize is recorded + persisted
        app.on_splitter_resized(Splitter.Resized("thread", 55))
        await pilot.pause()
        assert app.config.thread_width == 55
        assert "thread_width = 55" in cfg_path.read_text()


async def test_clicking_a_message_selects_it():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "first"),
                        RemoteMessage("2.0", "u", "second")]},
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        pane = app.query_one("#messages", MessagePane)
        assert pane.selected_message().ts == "2.0"   # defaults to newest
        await pilot.click(pane._widgets[0])          # click the first message
        await pilot.pause()
        assert pane.selected_message().ts == "1.0"   # now selected
        assert app.focused is pane                   # clicking focuses the pane


async def test_reply_indicator_is_a_clickable_open_thread_action():
    from slak.ui.widgets import MessagePane
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        pane = app.query_one("#messages", MessagePane)
        body = pane._body(RemoteMessage("9.0", "u", "parent", reply_count=3))
        assert "@click=app.open_thread_at('9.0')" in body
        assert "💬 3 replies" in body


async def test_action_open_thread_at_opens_that_thread():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        ts = app.query_one("#messages", MessagePane)._messages[0].ts
        await app.action_open_thread_at(ts)
        for _ in range(3):
            await pilot.pause()
        assert app.query_one("#thread").display is True
        assert app.open_thread_ts == ts


async def test_opening_channel_highlights_its_sidebar_row():
    app = make_app()  # C1, C2
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app.open_channel("C2")
        await pilot.pause()
        assert app.query_one("#sidebar", Sidebar).highlighted_child.id == "C2"


async def test_compose_is_focused_on_launch():
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.focused, Input)
        assert app.focused.id == "compose"


async def test_typing_then_enter_posts_and_renders():
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "e", "y", "enter")
        for _ in range(3):
            await pilot.pause()
        history = await app.client.history("C1")
        assert history[-1].text == "hey"
        # the event worker consumed the NewMessage and mounted it (1 seeded + 1 new)
        pane = app.query_one("#messages", MessagePane)
        assert len(pane.children) == 2


def make_multi_app() -> PyslkApp:
    a = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "a-msg")]},
    )
    b = FakeSlackClient(
        "T2", "Beta",
        channels=[RemoteChannel("C9", "beta-chan")],
        history={"C9": [RemoteMessage("1.0", "u", "b-msg")]},
    )
    return PyslkApp(
        router=WorkspaceRouter([a, b], order=["T1", "T2"]),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_starts_on_first_workspace():
    app = make_multi_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app.router.active_team_id() == "T1"
        assert app.active_channel == "C1"


async def test_alt_number_switches_workspace_and_loads_its_channels():
    app = make_multi_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("alt+2")
        for _ in range(3):
            await pilot.pause()
        assert app.router.active_team_id() == "T2"
        assert app.active_channel == "C9"
        assert "beta-chan" in app._channel_names.values()


async def test_opening_channel_marks_it_read():
    app = make_app()  # C1 is opened on boot
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app.cache.get_workspace_read_state("T1")["C1"].has_unread is False


async def test_opening_channel_marks_read_on_the_server():
    app = make_app()  # C1 opened on boot, latest message ts 100.0
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        # conversations.mark was sent so Slack stops reporting it unread next launch
        assert ("C1", "100.0") in app.client.marks


async def test_message_to_inactive_channel_marks_it_unread():
    app = make_app()  # C1 active, C2 inactive
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await app.client.post_message("C2", "ping")  # arrives in an unopened channel
        for _ in range(3):
            await pilot.pause()
        assert app.cache.get_workspace_read_state("T1")["C2"].has_unread is True
        assert "C2" in app.query_one("#sidebar", Sidebar).unread_ids()


async def test_message_to_active_channel_is_not_marked_unread():
    app = make_app()  # C1 active
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await app.client.post_message("C1", "ping")  # the channel you're reading
        for _ in range(3):
            await pilot.pause()
        assert app.cache.get_workspace_read_state("T1")["C1"].has_unread is False


def make_msg_app() -> PyslkApp:
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [
            RemoteMessage("1.0", "u", "one"),
            RemoteMessage("2.0", "u", "two"),
            RemoteMessage("3.0", "u", "three"),
        ]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_arrow_keys_select_messages_when_pane_focused():
    app = make_msg_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        pane = app.query_one("#messages", MessagePane)
        pane.focus()
        await pilot.pause()
        assert pane.selected_message().text == "three"  # newest selected by default
        await pilot.press("up")
        await pilot.pause()
        assert pane.selected_message().text == "two"
        await pilot.press("up", "up")  # clamp at oldest
        await pilot.pause()
        assert pane.selected_message().text == "one"


async def test_copy_selected_message_action():
    app = make_msg_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        captured = {}
        app.copy_to_clipboard = lambda text: captured.__setitem__("text", text)
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await pilot.press("up")  # select "two"
        await pilot.pause()
        app.action_copy_message()
        assert captured["text"] == "two"


async def test_escape_returns_focus_to_compose():
    app = make_msg_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused.id == "compose"


def make_thread_app() -> PyslkApp:
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [
            RemoteMessage("100.0", "u", "parent msg"),
            RemoteMessage("101.0", "a", "first reply", thread_ts="100.0"),
        ]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_main_pane_hides_thread_replies():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        # only the top-level parent shows in the main pane
        assert len(app.query_one("#messages", MessagePane).children) == 1


async def test_open_thread_shows_parent_and_replies():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await app.action_open_thread()
        for _ in range(3):
            await pilot.pause()
        thread = app.query_one("#thread")
        assert thread.display is True
        assert len(app.query_one("#thread-messages", MessagePane).children) == 2


async def test_esc_closes_open_thread_panel():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await app.action_open_thread()
        for _ in range(3):
            await pilot.pause()
        assert app.query_one("#thread").display is True
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#thread").display is False  # closed by Esc
        assert app.focused.id == "messages"  # focus returns to the message


async def test_opening_thread_keeps_focus_on_message_then_enters_reply():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        messages = app.query_one("#messages", MessagePane)
        messages.focus()
        await pilot.pause()
        await app.action_open_thread()  # first Enter: open, focus stays on message
        for _ in range(3):
            await pilot.pause()
        assert app.query_one("#thread").display is True
        assert app.focused is messages  # focus did not jump to the reply box
        await app.action_open_thread()  # second Enter: into the reply box
        await pilot.pause()
        assert app.focused.id == "thread-compose"


async def test_closing_thread_returns_focus_to_the_message():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        messages = app.query_one("#messages", MessagePane)
        messages.focus()
        await pilot.pause()
        await app.action_open_thread()  # opens, focus stays on the message
        for _ in range(3):
            await pilot.pause()
        app.action_close_thread()       # Esc closes the panel
        await pilot.pause()
        assert app.query_one("#thread").display is False
        assert app.focused is messages  # focus did not jump to the compose box


async def test_replying_in_thread_posts_threaded_and_appends():
    app = make_thread_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await app.action_open_thread()
        for _ in range(3):
            await pilot.pause()
        app.query_one("#thread-compose", Input).focus()
        await pilot.pause()
        await pilot.press("y", "o", "enter")
        for _ in range(4):
            await pilot.pause()
        replies = await app.client.thread_replies("C1", "100.0")
        assert replies[-1].text == "yo"
        assert replies[-1].thread_ts == "100.0"
        assert len(app.query_one("#thread-messages", MessagePane).children) == 3


async def test_user_names_resolved_on_load():
    from slak.slack import RemoteUser
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "U1", "hi")]},
        users=[RemoteUser("U1", "Alice")],
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app._name_of("U1") == "Alice"


async def test_unknown_author_resolved_asynchronously():
    from slak.slack import RemoteUser
    client = FakeSlackClient("T1", "Acme", users=[RemoteUser("U9", "Zoe")])
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._names["T1"].pop("U9", None)  # simulate not-yet-known author
        assert app._name_of("U9") == "U9"
        await app._resolve_user(client, "U9")
        assert app._name_of("U9") == "Zoe"


async def test_reaction_event_updates_displayed_message():
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "alice", "hi")]},
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await client.add_reaction("C1", "100.0", "tada")
        for _ in range(3):
            await pilot.pause()
        pane = app.query_one("#messages", MessagePane)
        assert any(r.emoji == "tada" for r in pane._messages[0].reactions)


async def test_reaction_picker_renders_custom_emoji_via_custom_render():
    from textual.widgets import OptionList
    from slak.ui.widgets import ReactionPicker

    app = make_app()
    ensured = []

    def fake_custom_render(name):
        return f"<img:{name}>" if name == "parrot" else None

    async def fake_ensure(names):
        ensured.append(list(names))
        return False

    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.push_screen(ReactionPicker(
            recent=["parrot"], customs=["parrot"],
            custom_render=fake_custom_render, ensure_custom=fake_ensure))
        for _ in range(2):
            await pilot.pause()
        results = app.screen.query_one("#react-results", OptionList)
        labels = [str(results.get_option_at_index(i).prompt)
                  for i in range(results.option_count)]
        assert any("<img:parrot>" in s for s in labels)  # custom image markup, not plain text
        assert ensured and "parrot" in ensured[0]         # its image was prefetched


async def test_reaction_picker_returns_highlighted_emoji():
    from slak.ui.widgets import ReactionPicker
    app = make_app()
    result = {}
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.push_screen(ReactionPicker(), lambda v: result.__setitem__("v", v))
        await pilot.pause()
        await pilot.press("t", "a", "d", "a", "enter")  # match :tada: then accept
        await pilot.pause()
        assert result["v"] == "tada"


async def test_reaction_picker_falls_back_to_raw_typed_name():
    from slak.ui.widgets import ReactionPicker
    app = make_app()
    result = {}
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.push_screen(ReactionPicker(), lambda v: result.__setitem__("v", v))
        await pilot.pause()
        # a custom-ish name with no standard match — still react with the raw name
        await pilot.press(*list("zzunknownzz"), "enter")
        await pilot.pause()
        assert result["v"] == "zzunknownzz"


def make_search_app() -> PyslkApp:
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [
            RemoteMessage("1.0", "u", "alpha match"),
            RemoteMessage("2.0", "u", "unrelated"),
            RemoteMessage("3.0", "u", "beta match"),
        ]},
    )
    return PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())


async def test_in_channel_search_jumps_to_newest_match():
    app = make_search_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("m", "a", "t", "c", "h", "enter")
        for _ in range(2):
            await pilot.pause()
        assert app.query_one("#messages", MessagePane).selected_message().text == "beta match"


async def test_search_next_steps_to_older_match():
    app = make_search_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("m", "a", "t", "c", "h", "enter")
        await pilot.pause()
        await pilot.press("down")  # next (older) match
        await pilot.pause()
        assert app.query_one("#messages", MessagePane).selected_message().text == "alpha match"


async def test_escape_closes_search_and_focuses_compose():
    app = make_search_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert app.query_one("#search").display is True
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#search").display is False
        assert app.focused.id == "compose"


def make_notify_app():
    from slak.notify import FakeNotifier
    from slak.slack import RemoteUser
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[
            RemoteChannel("C1", "general"),
            RemoteChannel("C2", "random"),
            RemoteChannel("D1", "alice", type="dm"),
        ],
        history={"C1": []},
        users=[RemoteUser("alice", "Alice")],
    )
    notifier = FakeNotifier()
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
        notifier=notifier,
    )
    return app, client, notifier


async def test_dm_from_other_user_notifies():
    app, client, notifier = make_notify_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await client.emit("D1", RemoteMessage("9.0", "alice", "hi there"))
        for _ in range(3):
            await pilot.pause()
        assert notifier.sent == [("Acme: Alice", "hi there")]


async def test_mention_in_inactive_channel_notifies():
    app, client, notifier = make_notify_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await client.emit("C2", RemoteMessage("9.0", "alice", "ping <@Uself>"))
        for _ in range(3):
            await pilot.pause()
        assert notifier.sent and notifier.sent[0][0] == "Acme: #random"


async def test_active_channel_and_self_do_not_notify():
    app, client, notifier = make_notify_app()  # C1 is active on boot
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await client.emit("C1", RemoteMessage("9.0", "alice", "hello <@Uself>"))  # active
        await client.emit("C2", RemoteMessage("9.1", "Uself", "my own note"))  # self
        for _ in range(3):
            await pilot.pause()
        assert notifier.sent == []


async def test_mark_unread_sets_dot_and_marks_remote():
    app = make_msg_app()  # C1 with one/two/three
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await pilot.press("up")  # select "two"
        await pilot.pause()
        app.action_mark_unread()
        for _ in range(3):
            await pilot.pause()
        assert app.cache.get_workspace_read_state("T1")["C1"].has_unread is True
        assert "C1" in app.query_one("#sidebar", Sidebar).unread_ids()
        assert app.client.marks[-1] == ("C1", "1.0")  # boundary = ts before "two"


async def test_tab_title_reflects_unread():
    app = make_app()  # team "Acme Corp" -> AC; C1 active, C2 inactive
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app.title == "slak AC"
        await app.client.post_message("C2", "ping")  # unread in inactive channel
        for _ in range(3):
            await pilot.pause()
        assert app.title == "slak AC (1)"


async def test_app_closes_cache_on_exit():
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
    assert app.cache._conn is None  # closed cleanly on shutdown


async def test_presence_away_updates_state_and_client():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.action_presence_away()
        for _ in range(2):
            await pilot.pause()
        assert app._presence["T1"][0] == "away"
        assert app.client.presence == "away"


async def test_snooze_sets_dnd_and_suppresses_notifications():
    app, client, notifier = make_notify_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.action_snooze(30)
        await pilot.pause()
        assert app._presence["T1"][1] > 0  # dnd end in the future
        await client.emit("D1", RemoteMessage("9.0", "alice", "hi"))  # would normally notify
        for _ in range(3):
            await pilot.pause()
        assert notifier.sent == []  # suppressed during DND


async def test_rtm_dnd_event_updates_state():
    from slak.slack import DndChanged
    import time as _t
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await app.client.emit_event(DndChanged(enabled=True, end_ts=_t.time() + 3600))
        for _ in range(3):
            await pilot.pause()
        assert app._presence["T1"][1] > _t.time()


def make_mention_app() -> PyslkApp:
    from slak.slack import RemoteUser
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": []},
        users=[RemoteUser("U1", "Alice Anderson"), RemoteUser("U2", "Bob")],
    )
    return PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())


async def test_mention_autocomplete_detects_and_inserts():
    app = make_mention_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        inp = app.query_one("#compose")
        inp.value = "@al"
        inp.cursor_position = 3
        app._update_completion(inp)
        await pilot.pause()
        assert app._completion_active is True
        assert app.query_one("#completion-popup").display is True
        app.completion_accept()
        assert inp.value == "@Alice Anderson "
        assert app._completion_active is False


async def test_compose_translates_mentions_on_send():
    app = make_mention_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        inp = app.query_one("#compose")
        inp.value = "hi @Alice Anderson"  # trailing token has a space -> popup inactive
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()
        history = await app.client.history("C1")
        assert history[-1].text == "hi <@U1>"


async def test_workspace_search_jumps_to_result_channel():
    client = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
        history={
            "C1": [RemoteMessage("1.0", "u", "hello")],
            "C2": [RemoteMessage("2.0", "u", "find the needle here")],
        },
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert app.active_channel == "C1"
        app.action_search_workspace()
        for _ in range(3):
            await pilot.pause()
        app.screen.query_one("#ws-search-input").value = "needle"
        await pilot.press("enter")          # run search -> populate + focus list
        for _ in range(4):
            await pilot.pause()
        await pilot.press("enter")          # select first result
        for _ in range(4):
            await pilot.pause()
        assert app.active_channel == "C2"    # jumped to the channel with the match


async def test_emoji_autocomplete_inserts_shortcode():
    app = make_mention_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        inp = app.query_one("#compose")
        inp.value = ":rock"
        inp.cursor_position = 5
        app._update_completion(inp)
        await pilot.pause()
        assert app._completion_active is True
        assert app._completion_kind == ":"
        app.completion_accept()
        assert inp.value.startswith(":rock")  # replaced with a :name: shortcode
        assert inp.value.endswith(": ")
        assert app._completion_active is False


async def test_emoji_needs_two_chars():
    app = make_mention_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        inp = app.query_one("#compose")
        inp.value = ":r"  # only one char after ':' -> no popup
        inp.cursor_position = 2
        app._update_completion(inp)
        await pilot.pause()
        assert app._completion_active is False


async def test_failed_reaction_surfaces_a_toast():
    from slak.slack import SlackError
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()

        async def boom(*a):
            raise SlackError("invalid_name")

        app.client.add_reaction = boom
        captured = []
        app.notify = lambda *a, **k: captured.append((a, k))
        await app._add_reaction("C1", "1.0", "thumbs_up")
        assert captured  # error was surfaced, not swallowed
        assert "invalid_name" in str(captured[0])


async def test_reacting_again_with_same_emoji_removes_it():
    app = make_app()  # C1 with one message at ts 100.0
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        msg = app.query_one("#messages", MessagePane)._messages[0]
        await app._add_reaction("C1", "100.0", "tada")    # add
        for _ in range(2):
            await pilot.pause()
        assert any(r.emoji == "tada" for r in msg.reactions)
        await app._add_reaction("C1", "100.0", "tada")    # same again -> toggle off
        for _ in range(2):
            await pilot.pause()
        assert not any(r.emoji == "tada" for r in msg.reactions)


async def test_group_dm_name_formats_member_handles():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("G1", "mpdm-alice--bob-1", "group_dm")],
        history={"G1": [RemoteMessage("1.0", "U1", "hi")]},
        users=[RemoteUser("U1", "Alice", handle="alice"),
               RemoteUser("U2", "Bob", handle="bob")],
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert app._channel_names["G1"] == "Alice, Bob"


async def test_bot_id_message_resolves_name_via_bots_info():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "B1", "deploy ok")]},  # bot, no username
        bots={"B1": "CIBot"},
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(5):
            await pilot.pause()
        assert app._name_of("B1") == "CIBot"  # resolved via bots.info


async def test_bot_avatar_url_is_captured_from_bots_info():
    from slak.slack import RemoteBot
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "B1", "deploy ok")]},
        bots={"B1": RemoteBot(name="CIBot", avatar="https://x/bot72.png")},
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(5):
            await pilot.pause()
        assert app._avatar_urls.get("T1", {}).get("B1") == "https://x/bot72.png"


async def test_channel_header_shows_name_and_topic():
    from textual.widgets import Static
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general", topic="Daily standup")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=Config())
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        header = str(app.query_one("#header", Static).render())
        assert "general" in header
        assert "Daily standup" in header


def _image_app(file_opener, raw_json="", history=None, file_bytes=None,
               image_preview="gui"):
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history=history or {"C1": [RemoteMessage("1.0", "u", "look", raw_json=raw_json)]},
        file_bytes=file_bytes,
    )
    cfg = Config(); cfg.image_preview = image_preview
    return PyslkApp(
        router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"),
        config=cfg, file_opener=file_opener,
    )


async def test_space_downloads_and_opens_image_attachment():
    import os
    opened = []
    raw = json.dumps({"files": [{"mimetype": "image/png",
                                 "url_private": "https://x/full.png"}]})
    app = _image_app(opened.append, raw_json=raw, file_bytes={"https://x/full.png": b"PNGDATA"})
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await pilot.press("space")
        for _ in range(4):
            await pilot.pause()
        assert len(opened) == 1
        path = opened[0]
        assert path.endswith(".png")           # opened a local file, not the URL
        assert os.path.exists(path)
        with open(path, "rb") as fh:
            assert fh.read() == b"PNGDATA"      # authenticated download, written to disk


async def test_space_previews_full_res_after_arrow_navigation():
    opened = []
    raw = json.dumps({"files": [{"mimetype": "image/png",
                                 "thumb_360": "https://x/t360.png",
                                 "url_private": "https://x/full.png"}]})
    history = {"C1": [
        RemoteMessage("1.0", "u", "pic", raw_json=raw),  # image, not last
        RemoteMessage("2.0", "u", "later text"),
    ]}
    app = _image_app(opened.append, history=history,
                     file_bytes={"https://x/full.png": b"FULL", "https://x/t360.png": b"THUMB"},
                     image_preview="gui")
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.press("up")          # move selection off the last message
        await pilot.pause()
        assert app.query_one("#messages", MessagePane).selected_message().ts == "1.0"
        await pilot.press("space")
        for _ in range(4):
            await pilot.pause()
        assert len(opened) == 1
        with open(opened[0], "rb") as fh:
            assert fh.read() == b"FULL"      # full-res original, not the thumbnail


async def test_nickname_overrides_display_name_and_persists(tmp_path):
    from pathlib import Path
    cfg_path = tmp_path / "config.toml"
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "U1", "hi")]},
        users=[RemoteUser("U1", "Joni")],
    )
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"),
                   config=Config(), config_path=cfg_path)
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        assert app._name_of("U1") == "Joni"          # resolved Slack name
        app._apply_nickname("U1", "Boss")
        await pilot.pause()
        assert app._name_of("U1") == "Boss"           # nickname wins
        assert 'U1 = "Boss"' in cfg_path.read_text() or '"U1"' in cfg_path.read_text()
        body = app.query_one("#messages", MessagePane)._body(RemoteMessage("1.0", "U1", "hi"))
        assert "Boss" in body and "Joni" not in body


async def test_reaction_picker_shows_recent_when_empty_then_filters_on_type():
    from textual.widgets import OptionList
    from slak.ui.widgets import ReactionPicker

    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.push_screen(ReactionPicker(recent=["tada", "joy"]))
        for _ in range(2):
            await pilot.pause()
        results = app.screen.query_one("#react-results", OptionList)
        assert results.size.width < app.size.width  # centered card, not fullscreen

        def labels():
            return [str(results.get_option_at_index(i).prompt)
                    for i in range(results.option_count)]

        # empty query -> the recent emoji
        assert any("tada" in s for s in labels())
        assert any("joy" in s for s in labels())
        # typing filters across all emoji shortcodes
        app.screen.query_one("#react-input", Input).focus()
        await pilot.press("g", "r", "i", "n")
        await pilot.pause()
        assert any("grin" in s for s in labels())
        assert not any("tada" in s for s in labels())  # recent no longer shown


async def test_nickname_modal_returns_value_or_none():
    from slak.ui.widgets import NicknameModal
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        # submit a value
        screen = NicknameModal("Joni", "")
        fut = app.push_screen(screen)  # noqa
        await pilot.pause()
        app.screen.query_one("#nickname-input", Input).value = "Boss"
        await pilot.press("enter")
        await pilot.pause()
        # cancel path
        app.push_screen(NicknameModal("Joni", "Boss"))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert type(app.screen).__name__ != "NicknameModal"


async def test_colored_names_wraps_author_in_its_user_color():
    from slak.ui.widgets import user_color
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "U1", "hi")]},
        users=[RemoteUser("U1", "alice")],
    )
    cfg = Config(); cfg.colored_names = True
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=cfg)
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        body = app.query_one("#messages", MessagePane)._body(
            RemoteMessage("1.0", "U1", "hi"))
        assert user_color("U1") in body  # author tinted by its deterministic colour


async def test_colored_names_tints_user_mentions_in_body():
    from slak.ui.widgets import user_color
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "U1", "hi <@U2>")]},
        users=[RemoteUser("U1", "alice"), RemoteUser("U2", "bob")],
    )
    cfg = Config(); cfg.colored_names = True
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"), config=cfg)
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        body = app.query_one("#messages", MessagePane)._body(
            RemoteMessage("1.0", "U1", "hi <@U2>"))
        assert f"[{user_color('U2')}]@bob[/]" in body  # mention tinted by U2's colour


async def test_colored_names_off_by_default_leaves_author_uncolored():
    from slak.ui.widgets import user_color
    app = make_app()  # default config: colored_names off
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        body = app.query_one("#messages", MessagePane)._body(
            RemoteMessage("1.0", "U1", "hi"))
        assert user_color("U1") not in body


async def test_image_preview_modal_shows_markup_and_closes_on_space():
    from textual.widgets import Static
    from slak.ui.widgets import ImagePreview

    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await app.push_screen(ImagePreview("IMG-MARKUP", caption="cat.png"))
        for _ in range(2):
            await pilot.pause()
        assert type(app.screen).__name__ == "ImagePreview"
        body = app.screen.query_one("#image-preview-body", Static)
        assert "IMG-MARKUP" in str(body.render())
        await pilot.press("space")          # Space closes the preview
        await pilot.pause()
        assert type(app.screen).__name__ != "ImagePreview"


async def test_gui_preview_mode_downloads_and_opens_file():
    import os
    opened = []
    raw = json.dumps({"files": [{"mimetype": "image/png",
                                 "url_private": "https://x/full.png"}]})
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "look", raw_json=raw)]},
        file_bytes={"https://x/full.png": b"PNGDATA"},
    )
    cfg = Config(); cfg.image_preview = "gui"
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"),
                   config=cfg, file_opener=opened.append)
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.press("space")
        for _ in range(4):
            await pilot.pause()
        assert len(opened) == 1 and opened[0].endswith(".png")


async def test_terminal_preview_mode_does_not_download_a_file():
    opened = []
    raw = json.dumps({"files": [{"mimetype": "image/png",
                                 "url_private": "https://x/full.png"}]})
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "look", raw_json=raw)]},
        file_bytes={"https://x/full.png": b"PNGDATA"},
    )
    cfg = Config()  # default image_preview == "terminal"
    app = PyslkApp(router=WorkspaceRouter.single(client), cache=Cache.open(":memory:"),
                   config=cfg, file_opener=opened.append)
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await app._preview_image_flow()
        await pilot.pause()
        assert opened == []  # terminal mode never shells out to an external viewer


async def test_space_with_no_image_does_not_open_a_preview():
    opened = []
    app = _image_app(opened.append, raw_json="")  # plain text message, no files
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one("#messages", MessagePane).focus()
        await pilot.pause()
        await app._preview_image_flow()
        await pilot.pause()
        assert opened == []
