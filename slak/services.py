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

"""Service helpers bridging the Slack client and the cache.

Pure, testable glue: message conversion, cache persistence, and the
reconnection backoff schedule. The app composes these; they hold no UI state.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator

from slak.cache import Cache, Message
from slak.slack import RemoteMessage, TOMBSTONE_TEXT


def to_cache_message(team_id: str, channel_id: str, rm: RemoteMessage) -> Message:
    return Message(
        ts=rm.ts,
        channel_id=channel_id,
        workspace_id=team_id,
        user_id=rm.user_id,
        text=rm.text,
        thread_ts=rm.thread_ts,
        reply_count=rm.reply_count,
        raw_json=rm.raw_json,
        is_deleted=rm.deleted,
    )


def typing_text(names: list[str]) -> str:
    """The typing-indicator line for the given display names (spec 04 §9)."""
    if not names:
        return ""
    if len(names) == 1:
        return f"{names[0]} is typing…"
    if len(names) == 2:
        return f"{names[0]} and {names[1]} are typing…"
    return "Several people are typing…"


def format_mpdm(name: str, lookup=None) -> str:
    """Format a Slack MPIM name (``mpdm-alice--bob--carol-1``) for display.

    Strips the ``mpdm-`` prefix and trailing ``-<index>``, splits the handles on
    ``--``, resolves each via ``lookup(handle)`` (falling back to the raw handle),
    and joins with ``, ``. Non-MPDM names pass through unchanged.
    """
    prefix = "mpdm-"
    if not name.startswith(prefix):
        return name
    body = name[len(prefix):]
    i = body.rfind("-")
    if i > 0 and body[i + 1:].isdigit():
        body = body[:i]
    handles = [h for h in body.split("--") if h]
    if not handles:
        return name
    displays = [(lookup(h) if lookup else None) or h for h in handles]
    return ", ".join(displays)


def _username_from_raw(raw_json: str) -> str:
    """Bot/app display-name override stored in a message's raw payload."""
    if not raw_json:
        return ""
    try:
        d = json.loads(raw_json)
    except (ValueError, TypeError):
        return ""
    return d.get("username") or d.get("bot_profile", {}).get("name", "")


def to_remote_message(m: Message) -> RemoteMessage:
    # legacy rows stored Slack's tombstone text with is_deleted=0; treat that as
    # deleted too, and never surface the placeholder body
    deleted = m.is_deleted or m.text == TOMBSTONE_TEXT
    return RemoteMessage(
        ts=m.ts,
        user_id=m.user_id,
        text="" if m.text == TOMBSTONE_TEXT else m.text,
        thread_ts=m.thread_ts,
        reply_count=m.reply_count,
        raw_json=m.raw_json,
        username=_username_from_raw(m.raw_json),
        deleted=deleted,
    )


def persist_messages(
    cache: Cache, team_id: str, channel_id: str, messages: list[RemoteMessage]
) -> None:
    for rm in messages:
        cache.add_message(to_cache_message(team_id, channel_id, rm))


async def backfill(
    client,
    cache: Cache,
    team_id: str,
    channel_ids: list[str] | None = None,
    concurrency: int = 4,
    cap: int = 500,
) -> int:
    """Fetch each channel's history since its newest cached message (spec 02 §6).

    Runs with a bounded worker pool; persists fetched messages (idempotent upsert)
    and returns the total number of messages fetched. A channel fetch that errors
    is skipped, not fatal.
    """
    if channel_ids is None:
        channel_ids = cache.channels_with_messages(team_id)
    sem = asyncio.Semaphore(concurrency)

    async def one(channel_id: str) -> int:
        oldest = cache.latest_message_ts(channel_id)
        async with sem:
            try:
                fetched = await client.history(channel_id, limit=cap, oldest=oldest)
            except Exception:
                return 0
        persist_messages(cache, team_id, channel_id, fetched)
        return len(fetched)

    counts = await asyncio.gather(*(one(c) for c in channel_ids))
    return sum(counts)


def backoff_delays(start: float = 1.0, cap: float = 30.0) -> Iterator[float]:
    """Yield reconnection delays: ``start`` doubling up to ``cap``, then holding.

    e.g. 1, 2, 4, 8, 16, 30, 30, … Reset by creating a fresh iterator on a
    successful connection.
    """
    delay = start
    while True:
        yield min(delay, cap)
        delay = min(delay * 2, cap)


_BROADCASTS = {
    "@here": "<!here>",
    "@channel": "<!channel>",
    "@everyone": "<!everyone>",
}


def translate_mentions(text: str, name_to_id: dict[str, str]) -> str:
    """Convert ``@Display Name`` → ``<@UID>`` and ``@here`` → ``<!here>``.

    Display names are replaced longest-first so a short name can't shadow a
    longer one that contains it.
    """
    for name in sorted(name_to_id, key=len, reverse=True):
        text = text.replace(f"@{name}", f"<@{name_to_id[name]}>")
    for token, wire in _BROADCASTS.items():
        text = text.replace(token, wire)
    return text


def window_title(initials: str, active_count: int, other_count: int) -> str:
    """Terminal title: ``slak <INITIALS> (active) +other`` (parts omitted at 0)."""
    if not initials:
        return "slak"
    out = f"slak {initials}"
    if active_count > 0:
        out += f" ({active_count})"
    if other_count > 0:
        out += f" +{other_count}"
    return out


async def reconnect_loop(
    run_once: Callable[[], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]],
    *,
    cap: float = 30.0,
    max_attempts: int | None = None,
) -> None:
    """Run ``run_once`` forever, reconnecting with exponential backoff.

    ``run_once`` is expected to connect and return when the connection drops; a
    clean return resets the backoff, while an exception escalates it. ``sleep``
    and ``max_attempts`` are injectable so the schedule is testable without real
    time or sockets.
    """
    delays = backoff_delays(cap=cap)
    attempts = 0
    while max_attempts is None or attempts < max_attempts:
        attempts += 1
        try:
            await run_once()
            delays = backoff_delays(cap=cap)  # clean session -> reset backoff
        except Exception:
            pass  # failed to connect / mid-session error -> keep escalating
        await sleep(next(delays))
