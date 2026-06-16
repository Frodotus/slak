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
from slak.ui.widgets import LinkPicker
from slak.workspace import WorkspaceRouter


def make_app(text: str):
    opened: list[str] = []
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme Corp",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "alice", text)]},
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
        url_opener=opened.append,
    )
    return app, opened


async def test_single_link_opens_directly():
    app, opened = make_app("ship it <https://example.com>")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+o")
        for _ in range(2):
            await pilot.pause()
        assert opened == ["https://example.com"]


async def test_no_links_opens_nothing():
    app, opened = make_app("just plain chatter")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+o")
        for _ in range(2):
            await pilot.pause()
        assert opened == []


async def test_multiple_links_show_picker_then_open_choice():
    app, opened = make_app("<https://a.com|A> and <https://b.com|B>")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, LinkPicker)
        await pilot.press("enter")  # first link highlighted
        for _ in range(2):
            await pilot.pause()
        assert opened == ["https://a.com"]
