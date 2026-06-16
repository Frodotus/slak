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
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage, RemoteUser
from slak.ui.widgets import MultiUserPicker
from slak.workspace import WorkspaceRouter


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "U2", "hello")]},
        users=[RemoteUser("U2", "bob"), RemoteUser("U3", "carol")],
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_ctrl_n_opens_composer():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+n")
        for _ in range(2):
            await pilot.pause()
        assert isinstance(app.screen, MultiUserPicker)


async def test_picking_one_user_opens_a_dm():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+n")
        for _ in range(2):
            await pilot.pause()
        await pilot.press("b", "o", "b")  # filter to bob
        await pilot.pause()
        await pilot.press("enter")  # quick-path: open DM with highlighted user
        for _ in range(4):
            await pilot.pause()
        assert app.active_channel == "DU2"


async def test_tab_toggles_multiple_then_enter_opens_group_dm():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+n")
        for _ in range(2):
            await pilot.pause()
        await pilot.press("tab")  # toggle first (bob)
        await pilot.press("down")
        await pilot.press("tab")  # toggle second (carol)
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert app.active_channel == "DU2-U3"
