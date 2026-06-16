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

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import (
    FakeSlackClient,
    RemoteChannel,
    RemoteMessage,
    RemoteUser,
    ThreadSub,
)
from slak.ui.widgets import MessagePane, ThreadList, ThreadPanel
from slak.ui.widgets import THREADS_ROW_ID
from slak.workspace import WorkspaceRouter


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={
            "C1": [
                RemoteMessage("100.0", "alice", "parent A"),
                RemoteMessage("101.0", "bob", "a reply", thread_ts="100.0"),
            ]
        },
        users=[RemoteUser("alice", "Alice"), RemoteUser("bob", "Bob")],
        thread_subs=[ThreadSub("C1", "100.0", last_read="100.0")],
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_sidebar_has_threads_landmark():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar")
        assert sidebar.get_child_by_id(THREADS_ROW_ID) is not None


async def test_entering_threads_view_swaps_panes_and_lists_threads():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app._enter_threads_view()
        for _ in range(2):
            await pilot.pause()
        assert app._view == "threads"
        threads = app.query_one("#threads", ThreadList)
        assert threads.display is True
        assert app.query_one("#messages", MessagePane).display is False
        assert len(threads._rows) == 1
        assert threads._rows[0].parent_text == "parent A"
        assert threads._rows[0].reply_count == 1


async def test_follow_cursor_shows_thread_in_panel():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app._enter_threads_view()
        for _ in range(3):
            await pilot.pause()
        panel = app.query_one("#thread", ThreadPanel)
        assert panel.display is True
        replies = panel.query_one("#thread-messages", MessagePane)
        assert len(replies._messages) == 2  # parent + 1 reply


async def test_opening_a_channel_exits_threads_view():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app._enter_threads_view()
        await pilot.pause()
        await app.open_channel("C1")
        await pilot.pause()
        assert app._view == "channels"
        assert app.active_channel == "C1"
        assert app.query_one("#threads", ThreadList).display is False
