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

from slak.cache import Cache, Message
from slak.services import backfill
from slak.slack import FakeSlackClient, RemoteMessage


def seeded_cache() -> Cache:
    cache = Cache.open(":memory:")
    cache.add_message(Message("100.0", "C1", "T1", user_id="u", text="old"))
    return cache


def test_channels_with_messages_and_latest_ts():
    cache = seeded_cache()
    cache.add_message(Message("150.0", "C1", "T1", user_id="u", text="newer"))
    cache.add_message(Message("90.0", "C2", "T1", user_id="u", text="other"))
    assert set(cache.channels_with_messages("T1")) == {"C1", "C2"}
    assert cache.latest_message_ts("C1") == "150.0"
    assert cache.latest_message_ts("Cx") == ""


async def test_fake_history_filters_by_oldest():
    client = FakeSlackClient(
        history={"C1": [RemoteMessage("100.0", "u", "a"), RemoteMessage("200.0", "u", "b")]}
    )
    got = await client.history("C1", oldest="100.0")
    assert [m.ts for m in got] == ["200.0"]  # strictly newer than oldest


async def test_backfill_persists_messages_since_latest_cached():
    cache = seeded_cache()  # C1 has 100.0
    client = FakeSlackClient(
        team_id="T1",
        history={"C1": [RemoteMessage("100.0", "u", "old"), RemoteMessage("200.0", "u", "new")]},
    )
    fetched = await backfill(client, cache, "T1")
    assert fetched == 1  # only the gap message
    texts = [m.text for m in cache.get_messages("C1")]
    assert texts == ["old", "new"]


async def test_backfill_no_op_when_nothing_new():
    cache = seeded_cache()
    client = FakeSlackClient(team_id="T1", history={"C1": [RemoteMessage("100.0", "u", "old")]})
    assert await backfill(client, cache, "T1") == 0
