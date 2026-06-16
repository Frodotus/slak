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
import pytest

from slak.slack import AuthError, RemoteChannel, Token
from slak.slack.http import HttpSlackClient, parse_rtm_event
from slak.slack import NewMessage


def make_client(handler):
    transport = httpx.MockTransport(handler)
    tok = Token("xoxc-tok", "dcookie", "T1", "Acme", "acme")
    return HttpSlackClient(tok, transport=transport)


async def test_attaches_bearer_and_cookie_to_workspace_host():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["cookie"] = request.headers.get("cookie")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "channels": []})

    await make_client(handler).list_channels()
    assert seen["auth"] == "Bearer xoxc-tok"
    assert "d=dcookie" in seen["cookie"]
    assert seen["url"] == "https://acme.slack.com/api/conversations.list"


async def test_list_channels_maps_types():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [
                    {"id": "C1", "name": "general", "is_channel": True},
                    {"id": "G1", "name": "secret", "is_private": True},
                    {"id": "D1", "name": "", "is_im": True, "user": "U9"},
                ],
            },
        )

    chans = await make_client(handler).list_channels()
    assert chans[0] == RemoteChannel("C1", "general", "channel")
    assert chans[1].type == "private"
    assert chans[2].type == "dm"
    assert chans[2].user == "U9"  # DM carries the peer user id for name resolution


async def test_history_returns_oldest_first_with_raw_json():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {"ts": "300.0", "user": "U1", "text": "third"},
                    {"ts": "100.0", "user": "U1", "text": "first"},
                    {"ts": "200.0", "user": "U1", "text": "second"},
                ],
            },
        )

    msgs = await make_client(handler).history("C1")
    assert [m.text for m in msgs] == ["first", "second", "third"]
    assert msgs[0].raw_json  # full payload preserved


async def test_post_message_sends_channel_and_text():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"ok": True, "ts": "999.0",
                  "message": {"ts": "999.0", "user": "Uself", "text": "hi"}},
        )

    msg = await make_client(handler).post_message("C1", "hi")
    assert seen["url"].endswith("/api/chat.postMessage")
    assert "channel=C1" in seen["body"]
    assert msg.ts == "999.0"


async def test_list_unread_channels_from_client_counts():
    def handler(request):
        return httpx.Response(200, json={
            "ok": True,
            "channels": [
                {"id": "C1", "has_unreads": True},
                {"id": "C2", "has_unreads": False},
            ],
            "mpims": [{"id": "G1", "has_unreads": True}],
            "ims": [{"id": "D1", "has_unreads": False},
                    {"id": "D2", "has_unreads": True}],
        })

    ids = await make_client(handler).list_unread_channels()
    assert set(ids) == {"C1", "G1", "D2"}


async def test_ok_false_auth_error_raises():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    with pytest.raises(AuthError):
        await make_client(handler).list_channels()


# --- RTM event parsing (pure) --------------------------------------------


def test_parse_rtm_message_event():
    event = parse_rtm_event(
        {"type": "message", "channel": "C1", "ts": "5.0", "user": "U1", "text": "yo"}
    )
    assert isinstance(event, NewMessage)
    assert event.channel_id == "C1"
    assert event.message.text == "yo"


def test_parse_rtm_ignores_non_message():
    assert parse_rtm_event({"type": "pref_change", "channel": "C1"}) is None


def test_parse_rtm_ignores_unhandled_message_subtypes():
    # joins/leaves carry a subtype we don't surface.
    assert parse_rtm_event(
        {"type": "message", "subtype": "channel_join", "channel": "C1"}
    ) is None


def test_parse_rtm_message_changed():
    from slak.slack import MessageEdited
    event = parse_rtm_event(
        {
            "type": "message",
            "subtype": "message_changed",
            "channel": "C1",
            "message": {"ts": "5.0", "user": "U1", "text": "edited"},
        }
    )
    assert isinstance(event, MessageEdited)
    assert (event.channel_id, event.ts, event.text) == ("C1", "5.0", "edited")


def test_parse_rtm_message_deleted():
    from slak.slack import MessageDeleted
    event = parse_rtm_event(
        {
            "type": "message",
            "subtype": "message_deleted",
            "channel": "C1",
            "deleted_ts": "5.0",
        }
    )
    assert isinstance(event, MessageDeleted)
    assert (event.channel_id, event.ts) == ("C1", "5.0")


async def test_update_message_calls_chat_update():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    await make_client(handler).update_message("C1", "5.0", "new text")
    assert seen["url"].endswith("/api/chat.update")
    assert "channel=C1" in seen["body"]
    assert "ts=5.0" in seen["body"]


async def test_delete_message_calls_chat_delete():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    await make_client(handler).delete_message("C1", "5.0")
    assert seen["url"].endswith("/api/chat.delete")
    assert "channel=C1" in seen["body"]
    assert "ts=5.0" in seen["body"]


def test_token_from_auth_test():
    from slak.slack.http import token_from_auth_test
    resp = {"ok": True, "team_id": "T1", "team": "Acme Corp",
            "url": "https://acme.slack.com/", "user_id": "U1"}
    tok = token_from_auth_test(resp, "xoxc-x", "dcookie")
    assert tok.team_id == "T1"
    assert tok.team_name == "Acme Corp"
    assert tok.team_domain == "acme"
    assert tok.access_token == "xoxc-x"
    assert tok.cookie == "dcookie"


async def test_thread_replies_oldest_first():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "messages": [
            {"ts": "100.0", "user": "u", "text": "parent"},
            {"ts": "102.0", "user": "b", "text": "reply2", "thread_ts": "100.0"},
            {"ts": "101.0", "user": "a", "text": "reply1", "thread_ts": "100.0"},
        ]})
    msgs = await make_client(handler).thread_replies("C1", "100.0")
    assert [m.text for m in msgs] == ["parent", "reply1", "reply2"]


async def test_post_message_includes_thread_ts_when_threaded():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "ts": "5.0",
                                         "message": {"ts": "5.0", "text": "hi"}})
    await make_client(handler).post_message("C1", "hi", thread_ts="100.0")
    assert "thread_ts=100.0" in seen["body"]


async def test_list_users_prefers_display_name_then_real_name():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "members": [
            {"id": "U1", "name": "alice", "profile": {"display_name": "Alice A."}},
            {"id": "U2", "name": "bob", "profile": {"display_name": "", "real_name": "Bob B."}},
            {"id": "U3", "name": "carol", "profile": {}},
        ]})
    users = await make_client(handler).list_users()
    by_id = {u.id: u.name for u in users}
    assert by_id == {"U1": "Alice A.", "U2": "Bob B.", "U3": "carol"}


async def test_history_parses_reactions():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "messages": [
            {"ts": "100.0", "user": "u", "text": "hi",
             "reactions": [{"name": "tada", "count": 2, "users": ["U1", "U2"]}]},
        ]})
    msg = (await make_client(handler).history("C1"))[0]
    assert msg.reactions[0].emoji == "tada"
    assert msg.reactions[0].count == 2


async def test_add_reaction_calls_api():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})
    await make_client(handler).add_reaction("C1", "100.0", "tada")
    assert seen["url"].endswith("/api/reactions.add")
    assert "name=tada" in seen["body"] and "timestamp=100.0" in seen["body"]


def test_parse_rtm_reaction_added_and_removed():
    from slak.slack import ReactionUpdated
    added = parse_rtm_event({"type": "reaction_added", "reaction": "tada",
                             "user": "U1", "item": {"channel": "C1", "ts": "100.0"}})
    assert isinstance(added, ReactionUpdated) and added.added
    assert added.channel_id == "C1" and added.ts == "100.0" and added.emoji == "tada"
    removed = parse_rtm_event({"type": "reaction_removed", "reaction": "tada",
                               "user": "U1", "item": {"channel": "C1", "ts": "100.0"}})
    assert removed.added is False


async def test_mark_calls_conversations_mark():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})
    await make_client(handler).mark("C1", "100.0")
    assert seen["url"].endswith("/api/conversations.mark")
    assert "channel=C1" in seen["body"] and "ts=100.0" in seen["body"]


async def test_set_presence_calls_api():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})
    await make_client(handler).set_presence("away")
    assert seen["url"].endswith("/api/users.setPresence")
    assert "presence=away" in seen["body"]


async def test_snooze_calls_api():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})
    await make_client(handler).set_snooze(30)
    assert "num_minutes=30" in seen["body"]


def test_parse_rtm_presence_and_dnd():
    from slak.slack import DndChanged, PresenceChanged
    p = parse_rtm_event({"type": "manual_presence_change", "presence": "away"})
    assert isinstance(p, PresenceChanged) and p.presence == "away"
    d = parse_rtm_event({"type": "dnd_updated_user",
                         "dnd_status": {"dnd_enabled": True, "next_dnd_end_ts": 123}})
    assert isinstance(d, DndChanged) and d.enabled and d.end_ts == 123


async def test_search_messages_parses_matches():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "messages": {"matches": [
            {"channel": {"id": "C1", "name": "general"}, "ts": "1.0",
             "user": "U1", "text": "deploy now"},
        ]}})
    res = await make_client(handler).search("deploy")
    assert seen["url"].endswith("/api/search.messages")
    assert "query=deploy" in seen["body"]
    assert res[0].channel_id == "C1"
    assert res[0].channel_name == "general"
    assert res[0].text == "deploy now"


async def test_list_custom_emoji_parses():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "emoji": {
            "thisisfine": "https://e/fine.png", "blob": "alias:thisisfine"}})
    res = await make_client(handler).list_custom_emoji()
    assert seen["url"].endswith("/api/emoji.list")
    assert res["thisisfine"] == "https://e/fine.png"
