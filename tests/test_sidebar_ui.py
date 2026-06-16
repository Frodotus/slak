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
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage
from slak.ui.widgets import Sidebar
from slak.workspace import WorkspaceRouter


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme Corp",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
        history={"C1": [RemoteMessage("100.0", "alice", "hello")]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_sidebar_visible_on_launch():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app.query_one("#sidebar", Sidebar).display is True


async def test_ctrl_b_hides_then_shows_sidebar():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)

        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.display is False

        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.display is True
