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
from slak.ui.widgets import WorkspaceSwitcher
from slak.workspace import WorkspaceRouter


def make_multi_app() -> PyslkApp:
    a = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "a-msg")]},
    )
    b = FakeSlackClient(
        "T2", "Globex",
        channels=[RemoteChannel("C9", "beta-chan")],
        history={"C9": [RemoteMessage("1.0", "u", "b-msg")]},
    )
    return PyslkApp(
        router=WorkspaceRouter([a, b], order=["T1", "T2"]),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_ctrl_w_opens_workspace_switcher():
    app = make_multi_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceSwitcher)


async def test_switcher_filters_and_enter_switches_workspace():
    app = make_multi_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app.router.active_team_id() == "T1"
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("g", "l", "o", "b")  # filter to "Globex"
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()
        assert app.router.active_team_id() == "T2"


async def test_switcher_escape_keeps_current_workspace():
    app = make_multi_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("escape")
        for _ in range(3):
            await pilot.pause()
        assert app.router.active_team_id() == "T1"
        assert not isinstance(app.screen, WorkspaceSwitcher)
