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

import pytest

from slak.slack import FakeSlackClient, NewMessage, RemoteChannel, RemoteMessage


@pytest.fixture
def client():
    return FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[
            RemoteChannel(id="C1", name="general", type="channel"),
            RemoteChannel(id="C2", name="random", type="channel"),
        ],
        history={
            "C1": [
                RemoteMessage(ts="200.0", user_id="U1", text="second"),
                RemoteMessage(ts="100.0", user_id="U1", text="first"),
            ]
        },
    )


async def test_lists_seeded_channels(client):
    chans = await client.list_channels()
    assert [c.name for c in chans] == ["general", "random"]


async def test_history_oldest_first(client):
    msgs = await client.history("C1")
    assert [m.text for m in msgs] == ["first", "second"]


async def test_post_appends_to_history(client):
    await client.post_message("C1", "third")
    msgs = await client.history("C1")
    assert msgs[-1].text == "third"


async def test_post_emits_new_message_event(client):
    await client.post_message("C2", "hello")
    event = await client.next_event()
    assert isinstance(event, NewMessage)
    assert event.channel_id == "C2"
    assert event.message.text == "hello"


def _threaded_client():
    return FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [
            RemoteMessage("100.0", "u", "parent"),
            RemoteMessage("101.0", "a", "reply1", thread_ts="100.0"),
            RemoteMessage("102.0", "b", "reply2", thread_ts="100.0"),
        ]},
    )


async def test_thread_replies_returns_parent_then_replies_oldest_first():
    replies = await _threaded_client().thread_replies("C1", "100.0")
    assert [m.text for m in replies] == ["parent", "reply1", "reply2"]


async def test_threaded_post_appends_reply_and_emits_event():
    client = _threaded_client()
    await client.post_message("C1", "reply3", thread_ts="100.0")
    replies = await client.thread_replies("C1", "100.0")
    assert replies[-1].text == "reply3"
    event = await client.next_event()
    assert event.message.thread_ts == "100.0"


async def test_list_users_returns_seeded_users():
    from slak.slack import RemoteUser
    c = FakeSlackClient(
        team_id="T1", team_name="Acme",
        users=[RemoteUser("U1", "Alice"), RemoteUser("U2", "Bob")],
    )
    users = await c.list_users()
    assert {u.id: u.name for u in users} == {"U1": "Alice", "U2": "Bob"}


async def test_user_info_looks_up_by_id():
    from slak.slack import RemoteUser
    c = FakeSlackClient(team_id="T1", users=[RemoteUser("U9", "Zoe")])
    assert (await c.user_info("U9")).name == "Zoe"
    assert await c.user_info("U404") is None


async def test_add_reaction_updates_message_and_emits_event():
    from slak.slack import ReactionUpdated
    c = FakeSlackClient("T1", "Acme", history={"C1": [RemoteMessage("100.0", "u", "hi")]})
    await c.add_reaction("C1", "100.0", "tada")
    msg = (await c.history("C1"))[0]
    assert msg.reactions[0].emoji == "tada" and msg.reactions[0].count == 1
    event = await c.next_event()
    assert isinstance(event, ReactionUpdated) and event.added and event.emoji == "tada"


async def test_remove_reaction_drops_it_at_zero():
    from slak.slack import Reaction
    c = FakeSlackClient(
        "T1", "Acme",
        history={"C1": [RemoteMessage("100.0", "u", "hi",
                                      reactions=[Reaction("tada", 1, ["Uself"])])]},
    )
    await c.remove_reaction("C1", "100.0", "tada")
    assert (await c.history("C1"))[0].reactions == []


async def test_mark_records_calls():
    c = FakeSlackClient("T1", "Acme")
    await c.mark("C1", "100.0")
    assert c.marks == [("C1", "100.0")]


async def test_presence_snooze_and_dnd_recorded():
    c = FakeSlackClient("T1", "Acme")
    await c.set_presence("away")
    await c.set_snooze(30)
    await c.end_dnd()
    assert c.presence == "away"
    assert c.snoozes == [30]
    assert c.dnd_ended is True


async def test_search_finds_matches_across_channels():
    from slak.slack import SearchResult
    c = FakeSlackClient(
        "T1", "Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
        history={
            "C1": [RemoteMessage("1.0", "u", "deploy now")],
            "C2": [RemoteMessage("2.0", "u", "random deploy chat")],
        },
    )
    res = await c.search("deploy")
    assert all(isinstance(r, SearchResult) for r in res)
    assert {r.channel_id for r in res} == {"C1", "C2"}


async def test_list_custom_emoji():
    c = FakeSlackClient(custom_emoji={
        "thisisfine": "https://e/fine.png",
        "blob": "alias:thisisfine",
    })
    assert await c.list_custom_emoji() == {
        "thisisfine": "https://e/fine.png", "blob": "alias:thisisfine"}
