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


def make_app(config_path):
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "alice", "hello")]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
        config_path=config_path,
    )


async def test_theme_pick_is_written_to_disk(tmp_path):
    path = tmp_path / "config.toml"
    app = make_app(path)
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+y")
        for _ in range(2):
            await pilot.pause()
        await pilot.press("d", "r", "a", "c")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()

    assert path.exists()
    reloaded = Config.loads(path.read_text())
    assert reloaded.resolve_theme("T1") == "dracula"


async def test_no_config_path_does_not_crash(tmp_path):
    # config_path=None: picking a theme still works, just isn't persisted.
    app = make_app(None)
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+y")
        for _ in range(2):
            await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()
        assert app._theme_name  # applied something, no exception
