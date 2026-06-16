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

import httpx

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import (
    FakeSlackClient,
    RemoteChannel,
    RemoteMessage,
    StarsChanged,
    Token,
)
from slak.slack.http import HttpSlackClient, parse_rtm_event
from slak.ui.widgets import Sidebar
from slak.workspace import WorkspaceRouter


async def test_fake_list_stars_returns_seeded():
    c = FakeSlackClient(stars=["C2", "D1"])
    assert await c.list_stars() == ["C2", "D1"]


async def test_http_list_stars_filters_to_channels_and_dms():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "items": [
            {"type": "channel", "channel": "C1"},
            {"type": "im", "channel": "D1"},
            {"type": "message", "channel": "C9", "message": {}},  # not a channel star
            {"type": "file", "file": {}},
        ]})

    tok = Token(access_token="x", cookie="d", team_id="T1", team_name="A", team_domain="a")
    client = HttpSlackClient(tok, transport=httpx.MockTransport(handler))
    assert await client.list_stars() == ["C1", "D1"]


def test_parse_rtm_star_events():
    assert isinstance(parse_rtm_event({"type": "star_added"}), StarsChanged)
    assert isinstance(parse_rtm_event({"type": "star_removed"}), StarsChanged)


def make_app(stars) -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "eng-web")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
        stars=stars,
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_starred_channel_appears_only_in_starred_section():
    app = make_app(stars=["C2"])
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        # a Starred section exists and is first
        assert list(sidebar._section_ids.values())[0].endswith("Starred")
        # C2 is listed once (in Starred), not duplicated below
        items = [li.id for li in sidebar.query("ListItem")]
        assert items.count("C2") == 1


async def test_star_ws_event_refreshes_sidebar():
    app = make_app(stars=[])
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        assert not any("Starred" in v for v in sidebar._section_ids.values())
        app.client._stars = ["C2"]
        await app.client.emit_event(StarsChanged())
        for _ in range(4):
            await pilot.pause()
        assert any(v.endswith("Starred") for v in sidebar._section_ids.values())
