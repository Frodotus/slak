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
from slak.themes import get_theme
from slak.ui.widgets import ThemePicker
from slak.workspace import WorkspaceRouter


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme Corp",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "alice", "hello")]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_ctrl_y_opens_theme_picker():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+y")
        for _ in range(2):
            await pilot.pause()
        assert isinstance(app.screen, ThemePicker)


async def test_picking_theme_applies_and_records_for_workspace():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+y")
        for _ in range(2):
            await pilot.pause()
        await pilot.press("d", "r", "a", "c")  # filter to dracula
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()
        assert app._theme_name == "dracula"
        assert app.get_css_variables()["accent"] == get_theme("dracula")["accent"]
        assert app.config.resolve_theme("T1") == "dracula"


async def test_default_theme_pick_sets_global_default():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+shift+y")
        for _ in range(2):
            await pilot.pause()
        await pilot.press("n", "o", "r", "d")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()
        assert app.config.theme == "nord"
