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

"""Slack client layer.

Defines the transport-agnostic ``SlackClient`` Protocol the rest of the app
depends on, the wire DTOs, realtime event types, the auth ``Token`` model, and a
``FakeSlackClient`` used for offline development and tests. The real
browser-cookie + RTM implementation (``HttpSlackClient``) implements the same
Protocol and is swapped in at startup.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Reaction:
    emoji: str
    count: int
    users: list[str] = field(default_factory=list)


class SlackError(Exception):
    """A Slack API call returned ``ok: false``."""


class AuthError(SlackError):
    """Authentication failed/expired (e.g. invalid_auth, rotated cookie)."""


@dataclass
class Token:
    """Browser session credentials for one workspace."""

    access_token: str  # xoxc-…
    cookie: str  # value of the `d` cookie
    team_id: str
    team_name: str = ""
    team_domain: str = ""


@dataclass
class RemoteChannel:
    id: str
    name: str
    type: str = "channel"  # channel | private | dm | group_dm


@dataclass
class RemoteMessage:
    ts: str
    user_id: str
    text: str
    thread_ts: str = ""
    raw_json: str = ""
    reactions: list[Reaction] = field(default_factory=list)


@dataclass
class RemoteUser:
    id: str
    name: str  # best display name (display_name › real_name › handle)
    is_bot: bool = False
    deleted: bool = False


@dataclass
class SearchResult:
    channel_id: str
    channel_name: str
    ts: str
    user_id: str
    text: str


# --- realtime events ------------------------------------------------------


@dataclass
class NewMessage:
    channel_id: str
    message: RemoteMessage


@dataclass
class Connected:
    team_id: str


@dataclass
class ReactionUpdated:
    channel_id: str
    ts: str
    emoji: str
    user_id: str
    added: bool


@dataclass
class MessageEdited:
    channel_id: str
    ts: str
    text: str


@dataclass
class MessageDeleted:
    channel_id: str
    ts: str


@dataclass
class PresenceChanged:
    presence: str  # "auto" | "away"


@dataclass
class DndChanged:
    enabled: bool
    end_ts: float


Event = (
    NewMessage
    | Connected
    | ReactionUpdated
    | MessageEdited
    | MessageDeleted
    | PresenceChanged
    | DndChanged
)


@runtime_checkable
class SlackClient(Protocol):
    team_id: str
    team_name: str
    self_user_id: str

    async def list_channels(self) -> list[RemoteChannel]: ...

    async def history(self, channel_id: str, limit: int = 50) -> list[RemoteMessage]: ...

    async def thread_replies(
        self, channel_id: str, thread_ts: str
    ) -> list[RemoteMessage]: ...

    async def post_message(
        self, channel_id: str, text: str, thread_ts: str = ""
    ) -> RemoteMessage: ...

    async def list_users(self) -> list[RemoteUser]: ...

    async def user_info(self, user_id: str) -> RemoteUser | None: ...

    async def add_reaction(self, channel_id: str, ts: str, emoji: str) -> None: ...

    async def remove_reaction(self, channel_id: str, ts: str, emoji: str) -> None: ...

    async def mark(self, channel_id: str, ts: str) -> None: ...

    async def update_message(self, channel_id: str, ts: str, text: str) -> None: ...

    async def delete_message(self, channel_id: str, ts: str) -> None: ...

    async def open_conversation(self, user_ids: list[str]) -> RemoteChannel: ...

    async def search(self, query: str) -> list[SearchResult]: ...

    async def list_custom_emoji(self) -> dict[str, str]: ...

    async def set_presence(self, presence: str) -> None: ...

    async def set_snooze(self, minutes: int) -> None: ...

    async def end_dnd(self) -> None: ...

    async def next_event(self) -> Event: ...


class FakeSlackClient:
    """In-memory client for offline development and tests."""

    def __init__(
        self,
        team_id: str = "T1",
        team_name: str = "Fake",
        channels: list[RemoteChannel] | None = None,
        history: dict[str, list[RemoteMessage]] | None = None,
        users: list[RemoteUser] | None = None,
        custom_emoji: dict[str, str] | None = None,
    ):
        self.team_id = team_id
        self.team_name = team_name
        self._channels = channels or []
        # store newest-first internally, normalize on read
        self._history: dict[str, list[RemoteMessage]] = history or {}
        self._users = {u.id: u for u in (users or [])}
        self._custom_emoji = custom_emoji or {}
        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self._self_user = "Uself"
        self.self_user_id = "Uself"
        self.marks: list[tuple[str, str]] = []
        self.presence = "auto"
        self.snoozes: list[int] = []
        self.dnd_ended = False

    async def list_channels(self) -> list[RemoteChannel]:
        return list(self._channels)

    async def history(self, channel_id: str, limit: int = 50) -> list[RemoteMessage]:
        msgs = sorted(self._history.get(channel_id, []), key=lambda m: float(m.ts))
        return msgs[-limit:]

    async def thread_replies(self, channel_id: str, thread_ts: str) -> list[RemoteMessage]:
        msgs = [
            m
            for m in self._history.get(channel_id, [])
            if m.ts == thread_ts or m.thread_ts == thread_ts
        ]
        return sorted(msgs, key=lambda m: float(m.ts))

    async def post_message(
        self, channel_id: str, text: str, thread_ts: str = ""
    ) -> RemoteMessage:
        msg = RemoteMessage(
            ts=f"{time.time():.6f}", user_id=self._self_user, text=text, thread_ts=thread_ts
        )
        self._history.setdefault(channel_id, []).append(msg)
        await self._events.put(NewMessage(channel_id=channel_id, message=msg))
        return msg

    def _find(self, channel_id: str, ts: str) -> RemoteMessage | None:
        for m in self._history.get(channel_id, []):
            if m.ts == ts:
                return m
        return None

    async def add_reaction(self, channel_id: str, ts: str, emoji: str) -> None:
        msg = self._find(channel_id, ts)
        if msg is None:
            return
        for r in msg.reactions:
            if r.emoji == emoji:
                if self._self_user not in r.users:
                    r.users.append(self._self_user)
                    r.count += 1
                break
        else:
            msg.reactions.append(Reaction(emoji=emoji, count=1, users=[self._self_user]))
        await self._events.put(
            ReactionUpdated(channel_id, ts, emoji, self._self_user, added=True)
        )

    async def remove_reaction(self, channel_id: str, ts: str, emoji: str) -> None:
        msg = self._find(channel_id, ts)
        if msg is None:
            return
        for r in list(msg.reactions):
            if r.emoji == emoji:
                if self._self_user in r.users:
                    r.users.remove(self._self_user)
                    r.count -= 1
                if r.count <= 0:
                    msg.reactions.remove(r)
                break
        await self._events.put(
            ReactionUpdated(channel_id, ts, emoji, self._self_user, added=False)
        )

    async def update_message(self, channel_id: str, ts: str, text: str) -> None:
        msg = self._find(channel_id, ts)
        if msg is None:
            return
        msg.text = text
        await self._events.put(MessageEdited(channel_id, ts, text))

    async def delete_message(self, channel_id: str, ts: str) -> None:
        msgs = self._history.get(channel_id, [])
        self._history[channel_id] = [m for m in msgs if m.ts != ts]
        await self._events.put(MessageDeleted(channel_id, ts))

    async def open_conversation(self, user_ids: list[str]) -> RemoteChannel:
        cid = "D" + "-".join(user_ids)
        name = ", ".join(
            self._users[u].name if u in self._users else u for u in user_ids
        )
        ctype = "dm" if len(user_ids) == 1 else "group_dm"
        ch = RemoteChannel(cid, name, ctype)
        if ch.id not in {c.id for c in self._channels}:
            self._channels.append(ch)
        self._history.setdefault(cid, [])
        return ch

    async def list_users(self) -> list[RemoteUser]:
        return list(self._users.values())

    async def user_info(self, user_id: str) -> RemoteUser | None:
        return self._users.get(user_id)

    async def mark(self, channel_id: str, ts: str) -> None:
        self.marks.append((channel_id, ts))

    async def search(self, query: str) -> list[SearchResult]:
        names = {c.id: c.name for c in self._channels}
        results: list[SearchResult] = []
        for channel_id, msgs in self._history.items():
            for m in msgs:
                if query.lower() in m.text.lower():
                    results.append(SearchResult(
                        channel_id=channel_id,
                        channel_name=names.get(channel_id, channel_id),
                        ts=m.ts, user_id=m.user_id, text=m.text,
                    ))
        return sorted(results, key=lambda r: float(r.ts), reverse=True)

    async def list_custom_emoji(self) -> dict[str, str]:
        return dict(self._custom_emoji)

    async def set_presence(self, presence: str) -> None:
        self.presence = presence

    async def set_snooze(self, minutes: int) -> None:
        self.snoozes.append(minutes)

    async def end_dnd(self) -> None:
        self.dnd_ended = True

    async def emit(self, channel_id: str, message: RemoteMessage) -> None:
        """Simulate an inbound message (from someone else) for tests/dev."""
        self._history.setdefault(channel_id, []).append(message)
        await self._events.put(NewMessage(channel_id=channel_id, message=message))

    async def emit_event(self, event: Event) -> None:
        """Push an arbitrary realtime event (tests/dev)."""
        await self._events.put(event)

    async def next_event(self) -> Event:
        return await self._events.get()


def demo_client() -> FakeSlackClient:
    """A small seeded fake so ``slak`` boots into something to look at."""
    return FakeSlackClient(
        team_id="T1",
        team_name="Acme Corp",
        users=[
            RemoteUser("alice", "Alice Anderson"),
            RemoteUser("bob", "Bob Brown"),
            RemoteUser("carol", "Carol Clark"),
            RemoteUser("dave", "Dave Davis"),
        ],
        channels=[
            RemoteChannel("C1", "general"),
            RemoteChannel("C2", "engineering"),
            RemoteChannel("C3", "random"),
            RemoteChannel("D1", "alice", type="dm"),
        ],
        history={
            "C1": [
                RemoteMessage("1718000100.0", "alice", "Morning all :wave:"),
                RemoteMessage("1718000200.0", "bob", "Deploy looks green ✅"),
                RemoteMessage("1718000300.0", "carol", "Nice work everyone"),
            ],
            "C2": [
                RemoteMessage("1718000050.0", "dave", "PR #214 is up for review"),
            ],
        },
    )
