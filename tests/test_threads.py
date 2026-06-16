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

from slak.cache import Cache, Channel, Message, ThreadSubscription


def fresh_cache() -> Cache:
    cache = Cache.open(":memory:")
    cache.upsert_channel(Channel(id="C1", workspace_id="T1", name="eng-platform"))
    cache.upsert_channel(Channel(id="C2", workspace_id="T1", name="random"))
    return cache


def sub(channel="C1", ts="100.0", last_read="", ws="T1") -> ThreadSubscription:
    return ThreadSubscription(
        workspace_id=ws, channel_id=channel, thread_ts=ts, last_read=last_read
    )


def test_upsert_and_list_active():
    cache = fresh_cache()
    cache.upsert_thread_subscription(sub(ts="100.0"))
    cache.upsert_thread_subscription(sub(ts="200.0"))
    active = cache.list_active_thread_subscriptions("T1")
    assert {s.thread_ts for s in active} == {"100.0", "200.0"}


def test_delete_removes_from_active():
    cache = fresh_cache()
    cache.upsert_thread_subscription(sub(ts="100.0"))
    cache.delete_thread_subscription("T1", "C1", "100.0")
    assert cache.list_active_thread_subscriptions("T1") == []


def test_reconcile_tombstones_missing_and_adds_fresh():
    cache = fresh_cache()
    cache.upsert_thread_subscription(sub(ts="100.0"))  # will go missing
    cache.reconcile_thread_subscriptions("T1", [sub(ts="200.0"), sub(ts="300.0")])
    active = {s.thread_ts for s in cache.list_active_thread_subscriptions("T1")}
    assert active == {"200.0", "300.0"}  # 100.0 tombstoned


def test_threads_overview_aggregates_and_sorts_by_last_reply():
    cache = fresh_cache()
    # thread A (parent 100.0 in C1) with two replies; last reply 102.0 by bob
    cache.add_message(Message("100.0", "C1", "T1", user_id="alice", text="parent A"))
    cache.add_message(Message("101.0", "C1", "T1", user_id="carol", text="r1", thread_ts="100.0"))
    cache.add_message(Message("102.0", "C1", "T1", user_id="bob", text="r2", thread_ts="100.0"))
    # thread B (parent 200.0 in C2) with one newer reply 250.0
    cache.add_message(Message("200.0", "C2", "T1", user_id="dave", text="parent B"))
    cache.add_message(Message("250.0", "C2", "T1", user_id="erin", text="r1", thread_ts="200.0"))
    cache.upsert_thread_subscription(sub(channel="C1", ts="100.0", last_read="102.0"))
    cache.upsert_thread_subscription(sub(channel="C2", ts="200.0", last_read="200.0"))

    rows = cache.threads_overview("T1")
    assert [r.thread_ts for r in rows] == ["200.0", "100.0"]  # newest last-reply first
    b, a = rows
    assert a.channel_name == "eng-platform"
    assert a.parent_text == "parent A"
    assert a.reply_count == 2
    assert a.last_reply_ts == "102.0"
    assert a.last_reply_user_id == "bob"
    assert a.unread is False  # last_read 102.0 == last reply
    assert b.unread is True  # 250.0 > last_read 200.0


def test_threads_overview_handles_missing_parent():
    cache = fresh_cache()
    cache.add_message(Message("101.0", "C1", "T1", user_id="carol", text="r1", thread_ts="100.0"))
    cache.upsert_thread_subscription(sub(channel="C1", ts="100.0"))
    (row,) = cache.threads_overview("T1")
    assert row.parent_text == ""  # parent not cached → placeholder handled in UI
    assert row.reply_count == 1
