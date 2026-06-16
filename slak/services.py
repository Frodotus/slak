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

from collections.abc import Awaitable, Callable, Iterator

from slak.cache import Cache, Message
from slak.slack import RemoteMessage


def to_cache_message(team_id: str, channel_id: str, rm: RemoteMessage) -> Message:
    return Message(
        ts=rm.ts,
        channel_id=channel_id,
        workspace_id=team_id,
        user_id=rm.user_id,
        text=rm.text,
        thread_ts=rm.thread_ts,
        raw_json=rm.raw_json,
    )


def to_remote_message(m: Message) -> RemoteMessage:
    return RemoteMessage(
        ts=m.ts,
        user_id=m.user_id,
        text=m.text,
        thread_ts=m.thread_ts,
        raw_json=m.raw_json,
    )


def persist_messages(
    cache: Cache, team_id: str, channel_id: str, messages: list[RemoteMessage]
) -> None:
    for rm in messages:
        cache.add_message(to_cache_message(team_id, channel_id, rm))


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
