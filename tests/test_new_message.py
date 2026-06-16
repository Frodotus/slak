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


async def test_fake_list_thread_subscriptions_returns_seeded():
    from slak.slack import ThreadSub

    c = FakeSlackClient(thread_subs=[ThreadSub("C1", "100.0", last_read="100.0")])
    subs = await c.list_thread_subscriptions()
    assert [(s.channel_id, s.thread_ts) for s in subs] == [("C1", "100.0")]


async def test_http_list_thread_subscriptions_paginates():
    pages = [
        {
            "ok": True,
            "threads": [{"root_msg": {"channel": "C1", "ts": "100.0"}, "last_read": "99.0"}],
            "response_metadata": {"next_cursor": "NEXT"},
        },
        {
            "ok": True,
            "threads": [{"root_msg": {"channel": "C2", "ts": "200.0"}, "last_read": "200.0"}],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    calls = {"n": 0}

    def handler(request):
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    subs = await make_http(handler).list_thread_subscriptions()
    assert calls["n"] == 2  # followed the cursor
    assert [(s.channel_id, s.thread_ts, s.last_read) for s in subs] == [
        ("C1", "100.0", "99.0"),
        ("C2", "200.0", "200.0"),
    ]


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
