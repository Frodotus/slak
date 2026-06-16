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


async def test_react_modal_returns_typed_emoji():
    from slak.ui.widgets import ReactionModal
    app = make_app()
    result = {}
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.push_screen(ReactionModal(), lambda v: result.__setitem__("v", v))
        await pilot.pause()
        await pilot.press("t", "a", "d", "a", "enter")
        await pilot.pause()
        assert result["v"] == "tada"


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
        assert app.client.marks == [("C1", "1.0")]  # boundary = ts before "two"


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
