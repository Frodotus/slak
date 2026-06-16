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

from slak.cache import Cache
from slak.services import (
    backoff_delays,
    persist_messages,
    to_cache_message,
    to_remote_message,
)
from slak.slack import RemoteMessage


def test_to_cache_message_carries_identifiers():
    rm = RemoteMessage(ts="1.0", user_id="U1", text="hi", thread_ts="0.5", raw_json="{}")
    m = to_cache_message("T1", "C1", rm)
    assert m.workspace_id == "T1"
    assert m.channel_id == "C1"
    assert (m.ts, m.user_id, m.text, m.thread_ts, m.raw_json) == (
        "1.0", "U1", "hi", "0.5", "{}",
    )


def test_to_remote_message_round_trips():
    rm = RemoteMessage(ts="1.0", user_id="U1", text="hi")
    back = to_remote_message(to_cache_message("T1", "C1", rm))
    assert (back.ts, back.user_id, back.text) == ("1.0", "U1", "hi")


def test_persist_messages_writes_to_cache_oldest_first():
    cache = Cache.open(":memory:")
    persist_messages(
        cache, "T1", "C1",
        [RemoteMessage("2.0", "U1", "b"), RemoteMessage("1.0", "U1", "a")],
    )
    assert [m.text for m in cache.get_messages("C1")] == ["a", "b"]
    cache.close()


def test_backoff_delays_exponential_capped_then_holds():
    gen = backoff_delays(cap=30.0)
    assert [next(gen) for _ in range(7)] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


async def test_reconnect_loop_escalates_on_failure_and_resets_after_clean_session():
    from slak.services import reconnect_loop

    slept = []
    outcomes = iter(["fail", "fail", "ok", "fail"])

    async def sleep(d):
        slept.append(d)

    async def run_once():
        if next(outcomes) == "fail":
            raise RuntimeError("connect failed")
        # "ok" returns normally => a clean session that later disconnected

    await reconnect_loop(run_once, sleep, max_attempts=4)
    # fail->1, fail->2, ok(reset)->1, fail->2
    assert slept == [1.0, 2.0, 1.0, 2.0]


def test_window_title_variants():
    from slak.services import window_title
    assert window_title("AC", 0, 0) == "slak AC"
    assert window_title("AC", 3, 0) == "slak AC (3)"
    assert window_title("AC", 0, 1) == "slak AC +1"
    assert window_title("AC", 3, 2) == "slak AC (3) +2"
    assert window_title("", 0, 0) == "slak"


def test_translate_mentions_display_names_and_specials():
    from slak.services import translate_mentions
    names = {"Alice Anderson": "U1", "Bob": "U2"}
    assert translate_mentions("hi @Alice Anderson and @Bob", names) == "hi <@U1> and <@U2>"
    assert translate_mentions("ping @here please", names) == "ping <!here> please"
    assert translate_mentions("no mentions here", names) == "no mentions here"


def test_translate_mentions_prefers_longest_name():
    from slak.services import translate_mentions
    # "Al" must not shadow "Alice" — longest match wins
    names = {"Al": "U9", "Alice": "U1"}
    assert translate_mentions("hey @Alice", names) == "hey <@U1>"


# --- MPDM (group-DM) name formatting -------------------------------------
from slak.services import format_mpdm  # noqa: E402


def test_format_mpdm_joins_handles_when_unresolved():
    assert format_mpdm("mpdm-alice--bob--carol-1") == "alice, bob, carol"


def test_format_mpdm_resolves_handles_via_lookup():
    assert format_mpdm("mpdm-alice--bob-1", {"alice": "Alice"}.get) == "Alice, bob"


def test_format_mpdm_passes_through_non_mpdm_names():
    assert format_mpdm("eng-web") == "eng-web"
