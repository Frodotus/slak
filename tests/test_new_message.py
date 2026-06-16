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

from slak.slack import FakeSlackClient, RemoteUser, Token
from slak.slack.http import HttpSlackClient


async def test_fake_open_conversation_single_is_a_dm():
    c = FakeSlackClient(users=[RemoteUser("U2", "bob")])
    ch = await c.open_conversation(["U2"])
    assert ch.type == "dm"
    assert "bob" in ch.name
    # the new conversation is now listed
    assert ch.id in {x.id for x in await c.list_channels()}


async def test_fake_open_conversation_multi_is_a_group_dm():
    c = FakeSlackClient(users=[RemoteUser("U2", "bob"), RemoteUser("U3", "carol")])
    ch = await c.open_conversation(["U2", "U3"])
    assert ch.type == "group_dm"


def make_http(handler):
    tok = Token(
        access_token="xoxc-x",
        cookie="dcookie",
        team_id="T1",
        team_name="Acme",
        team_domain="acme",
    )
    return HttpSlackClient(tok, transport=httpx.MockTransport(handler))


async def test_http_open_conversation_calls_conversations_open():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "channel": {"id": "D9"}})

    ch = await make_http(handler).open_conversation(["U2", "U3"])
    assert seen["url"].endswith("/api/conversations.open")
    assert "users=U2%2CU3" in seen["body"] or "users=U2,U3" in seen["body"]
    assert ch.id == "D9"
