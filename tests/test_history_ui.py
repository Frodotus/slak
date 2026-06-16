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
from slak.workspace import WorkspaceRouter


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme Corp",
        channels=[
            RemoteChannel("C1", "general"),
            RemoteChannel("C2", "random"),
            RemoteChannel("C3", "design"),
        ],
        history={"C1": [RemoteMessage("100.0", "alice", "hello")]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_alt_left_and_right_walk_channel_history():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        assert app.active_channel == "C1"
        await app.open_channel("C2")
        await app.open_channel("C3")
        assert app.active_channel == "C3"

        await pilot.press("alt+left")
        await pilot.pause()
        assert app.active_channel == "C2"

        await pilot.press("alt+left")
        await pilot.pause()
        assert app.active_channel == "C1"

        await pilot.press("alt+right")
        await pilot.pause()
        assert app.active_channel == "C2"


async def test_new_navigation_truncates_forward_history():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await app.open_channel("C2")
        await app.open_channel("C3")
        await pilot.press("alt+left")  # back to C2
        await pilot.pause()
        await app.open_channel("C1")  # new navigation truncates C3

        await pilot.press("alt+right")  # nothing forward
        await pilot.pause()
        assert app.active_channel == "C1"
