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

from slak.cache import Cache, Channel, Message


@pytest.fixture
def cache():
    c = Cache.open(":memory:")
    yield c
    c.close()


def _msg(ts, text, channel="C1", ws="T1", user="U1", **kw):
    return Message(
        ts=ts, channel_id=channel, workspace_id=ws, user_id=user, text=text, **kw
    )


def test_messages_returned_oldest_first(cache):
    cache.add_message(_msg("100.0", "first"))
    cache.add_message(_msg("300.0", "third"))
    cache.add_message(_msg("200.0", "second"))
    texts = [m.text for m in cache.get_messages("C1")]
    assert texts == ["first", "second", "third"]


def test_get_messages_respects_limit_keeping_newest(cache):
    for i in range(5):
        cache.add_message(_msg(f"{100 + i}.0", f"m{i}"))
    texts = [m.text for m in cache.get_messages("C1", limit=2)]
    assert texts == ["m3", "m4"]


def test_get_messages_can_include_deleted(cache):
    cache.add_message(_msg("100.0", "kept"))
    cache.add_message(_msg("200.0", "gone"))
    cache.delete_message("C1", "200.0")
    # default: deleted ones are hidden
    assert [m.text for m in cache.get_messages("C1")] == ["kept"]
    # opt-in: keep them so they can render as a "(deleted)" tombstone
    msgs = cache.get_messages("C1", include_deleted=True)
    assert [m.text for m in msgs] == ["kept", "gone"]
    assert msgs[1].is_deleted is True


def test_add_message_upserts_in_place(cache):
    cache.add_message(_msg("100.0", "original"))
    cache.add_message(_msg("100.0", "edited", is_edited=True))
    msgs = cache.get_messages("C1")
    assert len(msgs) == 1
    assert msgs[0].text == "edited"
    assert msgs[0].is_edited is True


def test_raw_json_round_trips(cache):
    cache.add_message(_msg("100.0", "hi", raw_json='{"blocks":[]}'))
    assert cache.get_messages("C1")[0].raw_json == '{"blocks":[]}'


def test_read_state_update_and_read(cache):
    cache.upsert_channel(Channel(id="C1", workspace_id="T1", name="general"))
    cache.update_read_state("C1", last_read_ts="150.0", has_unread=True)
    state = cache.get_workspace_read_state("T1")
    assert state["C1"].has_unread is True
    assert state["C1"].last_read_ts == "150.0"


def test_marking_read_clears_unread(cache):
    cache.upsert_channel(Channel(id="C1", workspace_id="T1", name="general"))
    cache.update_read_state("C1", "150.0", True)
    cache.update_read_state("C1", "300.0", False)
    assert cache.get_workspace_read_state("T1")["C1"].has_unread is False


def test_workspaces_with_unreads(cache):
    cache.upsert_channel(Channel(id="C1", workspace_id="T1", name="a"))
    cache.upsert_channel(Channel(id="C2", workspace_id="T2", name="b"))
    cache.update_read_state("C1", "1.0", True)
    cache.update_read_state("C2", "1.0", False)
    assert cache.workspaces_with_unreads() == ["T1"]


def test_list_channels_for_workspace(cache):
    cache.upsert_channel(Channel(id="C1", workspace_id="T1", name="general"))
    cache.upsert_channel(Channel(id="C2", workspace_id="T1", name="random"))
    cache.upsert_channel(Channel(id="C9", workspace_id="T2", name="other"))
    names = sorted(c.name for c in cache.list_channels("T1"))
    assert names == ["general", "random"]


def test_search_finds_term_in_channel(cache):
    cache.add_message(_msg("1.0", "hello world"))
    cache.add_message(_msg("2.0", "goodbye world"))
    cache.add_message(_msg("3.0", "world elsewhere", channel="C2"))
    assert set(cache.search_messages("C1", "world")) == {"1.0", "2.0"}


def test_search_is_prefix(cache):
    cache.add_message(_msg("1.0", "deploying now"))
    assert "1.0" in cache.search_messages("C1", "deploy")


def test_search_multiple_terms_are_anded(cache):
    cache.add_message(_msg("1.0", "deploy the app"))
    cache.add_message(_msg("2.0", "deploy only"))
    assert cache.search_messages("C1", "deploy app") == ["1.0"]


def test_search_returns_newest_first(cache):
    cache.add_message(_msg("1.0", "first match"))
    cache.add_message(_msg("2.0", "second match"))
    assert cache.search_messages("C1", "match") == ["2.0", "1.0"]


def test_search_empty_query_returns_empty(cache):
    cache.add_message(_msg("1.0", "anything"))
    assert cache.search_messages("C1", "   ") == []


def test_open_rebuilds_a_corrupt_database(tmp_path):
    path = tmp_path / "cache.db"
    path.write_bytes(b"this is definitely not a sqlite database" * 50)
    cache = Cache.open(str(path))  # must not raise — rebuild instead
    cache.add_message(Message(ts="1.0", channel_id="C1", workspace_id="T1", text="ok"))
    assert [m.text for m in cache.get_messages("C1")] == ["ok"]
    cache.close()


def test_close_is_idempotent_and_persists(tmp_path):
    path = str(tmp_path / "c.db")
    c = Cache.open(path)
    c.add_message(Message(ts="1.0", channel_id="C1", workspace_id="T1", text="hi"))
    c.close()
    c.close()  # second close must not raise
    reopened = Cache.open(path)
    assert [m.text for m in reopened.get_messages("C1")] == ["hi"]
    reopened.close()


def test_open_rebuilds_stale_fts_index(tmp_path):
    import sqlite3
    from slak.cache import SCHEMA
    path = str(tmp_path / "c.db")
    # simulate a cache created before FTS existed: base schema + rows, no fts index
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO messages(ts, channel_id, workspace_id, text) "
        "VALUES ('1.0','C1','T1','hello world')"
    )
    conn.commit()
    conn.close()

    cache = Cache.open(path)
    # FTS was rebuilt from existing rows, so search finds the old message
    assert cache.search_messages("C1", "hello") == ["1.0"]
    # and re-adding it (the sync path) must not raise "database disk image is malformed"
    cache.add_message(Message(ts="1.0", channel_id="C1", workspace_id="T1", text="hello there"))
    assert cache.search_messages("C1", "there") == ["1.0"]
    cache.close()


def test_channel_visits_track_most_recent():
    cache = Cache.open(":memory:")
    assert cache.last_visited_channel("T1") is None
    cache.record_visit("T1", "C1")
    cache.record_visit("T1", "C2")
    cache.record_visit("T1", "C1")   # revisit bumps it to most recent
    assert cache.last_visited_channel("T1") == "C1"
    cache.record_visit("T1", "C3")
    assert cache.last_visited_channel("T1") == "C3"
    assert cache.last_visited_channel("T2") is None  # per-workspace


def test_visit_order_is_most_recent_first():
    cache = Cache.open(":memory:")
    cache.record_visit("T1", "C1")
    cache.record_visit("T1", "C2")
    cache.record_visit("T1", "C3")
    cache.record_visit("T1", "C1")  # revisit -> C1 jumps to front
    assert cache.visit_order("T1") == ["C1", "C3", "C2"]
