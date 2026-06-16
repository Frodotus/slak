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
from slak.sections import order_native_sections
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage, RemoteSection, Token
from slak.slack.http import HttpSlackClient
from slak.ui.widgets import Sidebar
from slak.workspace import WorkspaceRouter


def sec(id, type="standard", next_id="", name=None, channel_ids=None):
    return RemoteSection(
        id=id, name=name or id, type=type, next_id=next_id,
        channel_ids=channel_ids or [],
    )


def names(result):
    return [s.id for s in result]


def test_linked_list_order_is_honored():
    secs = [sec("B", next_id="C"), sec("A", next_id="B"), sec("C")]
    assert names(order_native_sections(secs)) == ["A", "B", "C"]


def test_multiple_heads_walk_in_input_order():
    secs = [sec("A", next_id="B"), sec("B"), sec("X", next_id="Y"), sec("Y")]
    assert names(order_native_sections(secs)) == ["A", "B", "X", "Y"]


def test_cycle_is_tolerated_each_section_once():
    secs = [sec("A", next_id="B"), sec("B", next_id="A")]
    assert sorted(names(order_native_sections(secs))) == ["A", "B"]
    assert len(names(order_native_sections(secs))) == 2


def test_hidden_types_dropped():
    secs = [sec("A"), sec("SC", type="slack_connect"), sec("SF", type="salesforce")]
    assert names(order_native_sections(secs)) == ["A"]


def test_recent_apps_only_when_non_empty():
    empty = [sec("apps", type="recent_apps")]
    assert order_native_sections(empty) == []
    full = [sec("apps", type="recent_apps", channel_ids=["C1"])]
    assert names(order_native_sections(full)) == ["apps"]


def test_stars_pinned_to_top():
    secs = [
        sec("chan", type="channels", next_id="star"),
        sec("star", type="stars", channel_ids=["C9"]),
    ]
    assert names(order_native_sections(secs)) == ["star", "chan"]


async def test_http_parses_channel_sections():
    def handler(request):
        return httpx.Response(200, json={
            "ok": True,
            "channel_sections": [
                {"channel_section_id": "Cs1", "name": "Eng", "type": "standard",
                 "next_channel_section_id": "Cs2", "channel_ids": ["C1", "C2"]},
                {"channel_section_id": "Cs2", "name": "DMs", "type": "direct_messages"},
            ],
        })

    tok = Token(access_token="x", cookie="d", team_id="T1", team_name="A", team_domain="a")
    client = HttpSlackClient(tok, transport=httpx.MockTransport(handler))
    secs = await client.list_channel_sections()
    assert [(s.id, s.name, s.next_id) for s in secs] == [
        ("Cs1", "Eng", "Cs2"), ("Cs2", "DMs", "")
    ]
    assert secs[0].channel_ids == ["C1", "C2"]


def test_parse_rtm_section_events():
    from slak.slack import SectionsChanged
    from slak.slack.http import parse_rtm_event

    for kind in ("channel_section_updated", "channel_sections_channels_added"):
        assert isinstance(parse_rtm_event({"type": kind}), SectionsChanged)
    assert parse_rtm_event({"type": "user_typing"}) is None


async def test_section_ws_event_refreshes_the_sidebar():
    from slak.slack import SectionsChanged

    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "eng-web")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
        sections=[RemoteSection("S1", "Engineering", "standard", channel_ids=["C2"])],
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        assert list(sidebar._section_ids.values()) == ["Engineering"]

        # sections change server-side, then a WS event arrives
        client._sections = [RemoteSection("S9", "Design", "standard", channel_ids=["C1"])]
        await client.emit_event(SectionsChanged())
        for _ in range(4):
            await pilot.pause()
        assert list(sidebar._section_ids.values()) == ["Design"]


async def test_app_renders_native_section_groups():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "eng-web"),
                  RemoteChannel("C3", "random")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
        sections=[
            RemoteSection("S1", "Engineering", "standard", next_id="S2",
                          channel_ids=["C2"]),
            RemoteSection("S2", "Channels", "channels", channel_ids=["C1"]),
        ],
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),  # use_slack_sections defaults True
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        # native section names are rendered as headers, Engineering before Channels
        labels = list(sidebar._section_ids.values())
        assert labels == ["Engineering", "Channels"]
