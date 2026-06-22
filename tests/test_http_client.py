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
    # users.conversations returns only joined channels (not every public channel)
    assert seen["url"] == "https://acme.slack.com/api/users.conversations"


async def test_list_all_public_channels_paginates_and_marks_membership():
    pages = [
        {"ok": True,
         "channels": [{"id": "C1", "name": "general", "is_channel": True, "is_member": True}],
         "response_metadata": {"next_cursor": "P2"}},
        {"ok": True, "channels": [
            {"id": "C2", "name": "random", "is_channel": True, "is_member": False},
            {"id": "C3", "name": "old", "is_channel": True, "is_archived": True},
        ]},
    ]
    state = {"n": 0, "urls": []}

    def handler(request):
        state["urls"].append(str(request.url))
        page = pages[state["n"]]; state["n"] += 1
        return httpx.Response(200, json=page)

    chans = await make_client(handler).list_all_public_channels()
    assert {c.id for c in chans} == {"C1", "C2"}          # archived C3 dropped
    by_id = {c.id: c for c in chans}
    assert by_id["C1"].is_member is True
    assert by_id["C2"].is_member is False
    assert state["urls"][0].endswith("/api/conversations.list")


def test_presence_events_single_and_batch():
    from slak.slack import PresenceChanged
    from slak.slack.http import presence_events
    assert presence_events({"type": "presence_change", "user": "U1", "presence": "active"}) \
        == [PresenceChanged(presence="active", user="U1")]
    batch = presence_events(
        {"type": "presence_change", "users": ["U1", "U2", "U3"], "presence": "away"})
    assert [e.user for e in batch] == ["U1", "U2", "U3"]
    assert all(e.presence == "away" for e in batch)


async def test_join_channel_calls_conversations_join():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "channel": {"id": "C9"}})

    await make_client(handler).join_channel("C9")
    assert seen["url"].endswith("/api/conversations.join")
    assert "channel=C9" in seen["body"]


async def test_list_channels_excludes_closed_dms_and_paginates():
    pages = [
        {"ok": True,
         "channels": [{"id": "C1", "name": "general", "is_channel": True}],
         "response_metadata": {"next_cursor": "PAGE2"}},
        {"ok": True, "channels": [
            {"id": "D1", "is_im": True, "user": "U9", "is_open": True},
            {"id": "D2", "is_im": True, "user": "U8", "is_open": False},  # hidden
        ]},
    ]
    state = {"n": 0, "bodies": []}

    def handler(request):
        state["bodies"].append(request.content.decode())
        page = pages[state["n"]]
        state["n"] += 1
        return httpx.Response(200, json=page)

    chans = await make_client(handler).list_channels()
    assert [c.id for c in chans] == ["C1", "D1"]   # closed DM D2 excluded
    assert state["n"] == 2                          # followed the cursor
    assert "cursor=PAGE2" in state["bodies"][1]


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


def test_parse_rtm_message_changed_to_tombstone_is_a_delete():
    # deleting a thread parent arrives as message_changed wrapping a tombstone —
    # it must be treated as a deletion, not an edit to "This message was deleted"
    from slak.slack import MessageDeleted
    event = parse_rtm_event(
        {
            "type": "message",
            "subtype": "message_changed",
            "channel": "C1",
            "message": {
                "subtype": "tombstone",
                "ts": "5.0",
                "text": "This message was deleted.",
            },
        }
    )
    assert isinstance(event, MessageDeleted)
    assert (event.channel_id, event.ts) == ("C1", "5.0")


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


def test_message_from_dict_marks_tombstone_deleted():
    # a deleted thread parent comes back from conversations.replies as a tombstone
    from slak.slack.http import _message_from_dict
    m = _message_from_dict(
        {"ts": "5.0", "subtype": "tombstone", "text": "This message was deleted."}
    )
    assert m.deleted is True
    assert m.text == ""  # drop Slack's placeholder; our renderer adds "(deleted)"


def test_message_from_dict_marks_sentinel_text_deleted():
    # belt-and-suspenders: the tombstone text even without the subtype
    from slak.slack.http import _message_from_dict
    m = _message_from_dict({"ts": "5.0", "text": "This message was deleted."})
    assert m.deleted is True
    assert m.text == ""


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


async def test_history_captures_bot_username():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "messages": [
            {"ts": "1.0", "bot_id": "B1", "username": "GitHub", "text": "deploy"},
        ]})
    msgs = await make_client(handler).history("C1")
    assert msgs[0].user_id == "B1"
    assert msgs[0].username == "GitHub"


async def test_bot_info_returns_name_and_avatar():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "bot": {
            "id": "B1", "name": "CI Bot",
            "icons": {"image_36": "u/36.png", "image_72": "u/72.png"},
        }})
    bot = await make_client(handler).bot_info("B1")
    assert bot.name == "CI Bot"
    assert bot.avatar == "u/72.png"  # prefers the larger icon


async def test_list_channels_excludes_archived():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "channels": [
            {"id": "C1", "name": "general", "is_channel": True},
            {"id": "C2", "name": "old-stuff", "is_channel": True, "is_archived": True},
        ]})
    chans = await make_client(handler).list_channels()
    assert [c.id for c in chans] == ["C1"]  # archived dropped


async def test_list_channels_captures_topic():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "channels": [
            {"id": "C1", "name": "general", "is_channel": True,
             "topic": {"value": "Daily standup"}},
        ]})
    chans = await make_client(handler).list_channels()
    assert chans[0].topic == "Daily standup"


async def test_list_users_captures_avatar():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "members": [
            {"id": "U1", "name": "alice", "profile": {"display_name": "Alice",
             "image_72": "https://x/alice.png"}},
        ]})
    users = await make_client(handler).list_users()
    assert users[0].avatar == "https://x/alice.png"
