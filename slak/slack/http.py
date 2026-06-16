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

"""Real Slack client over the internal browser protocol.

Authenticates with a browser ``xoxc`` token (bearer) + ``d`` cookie against the
workspace host, and exposes the same ``SlackClient`` Protocol as the fake. Web API
calls are async httpx POSTs; realtime arrives over an RTM websocket whose frames
are parsed by :func:`parse_rtm_event` and pushed onto an internal queue that
``next_event`` drains.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from slak.slack import (
    AuthError,
    Connected,
    Event,
    MessageDeleted,
    MessageEdited,
    NewMessage,
    DndChanged,
    RemoteSection,
    SectionsChanged,
    PresenceChanged,
    Reaction,
    ReactionUpdated,
    RemoteChannel,
    RemoteMessage,
    RemoteUser,
    SearchResult,
    SlackError,
    ThreadSub,
    Token,
)

_AUTH_ERRORS = {"invalid_auth", "not_authed", "account_inactive", "token_revoked"}


def _channel_type(c: dict) -> str:
    if c.get("is_im"):
        return "dm"
    if c.get("is_mpim"):
        return "group_dm"
    if c.get("is_private"):
        return "private"
    return "channel"


def token_from_auth_test(resp: dict, access_token: str, cookie: str) -> Token:
    """Build a :class:`Token` from an ``auth.test`` response + credentials."""
    url = resp.get("url", "")
    domain = url.split("://", 1)[-1].split(".slack.com", 1)[0]
    return Token(
        access_token=access_token,
        cookie=cookie,
        team_id=resp.get("team_id", ""),
        team_name=resp.get("team", ""),
        team_domain=domain,
    )


async def fetch_team_info(access_token: str, cookie: str, transport=None) -> dict:
    """Call ``auth.test`` on the generic host to validate creds and learn the team."""
    async with httpx.AsyncClient(
        base_url="https://slack.com/api/",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies={"d": cookie},
        transport=transport,
        timeout=30.0,
    ) as http:
        resp = await http.post("auth.test")
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok", False):
        raise AuthError(data.get("error", "auth_test_failed"))
    return data


def _message_from_dict(m: dict) -> RemoteMessage:
    return RemoteMessage(
        ts=m.get("ts", ""),
        user_id=m.get("user", m.get("bot_id", "")),
        text=m.get("text", ""),
        thread_ts=m.get("thread_ts", ""),
        raw_json=json.dumps(m),
        reactions=[
            Reaction(emoji=r.get("name", ""), count=r.get("count", 0),
                     users=list(r.get("users", [])))
            for r in m.get("reactions", [])
        ],
    )


def _user_from_member(m: dict) -> RemoteUser:
    prof = m.get("profile", {})
    name = (
        prof.get("display_name")
        or prof.get("real_name")
        or m.get("name")
        or m.get("id", "")
    )
    return RemoteUser(
        id=m.get("id", ""),
        name=name,
        is_bot=bool(m.get("is_bot")),
        deleted=bool(m.get("deleted")),
    )


def parse_rtm_event(data: dict) -> Event | None:
    """Parse one RTM frame into an Event, or None if we don't surface it.

    The basic feed surfaces plain new messages and connection (``hello``). Edits,
    deletes, joins (which carry a ``subtype``) and other event types are skipped
    here; richer handling lands with the reactions/edit slices.
    """
    kind = data.get("type")
    if kind == "hello":
        return Connected(team_id="")
    if kind == "manual_presence_change":
        return PresenceChanged(presence=data.get("presence", "auto"))
    if kind in ("dnd_updated", "dnd_updated_user"):
        status = data.get("dnd_status", {})
        return DndChanged(
            enabled=bool(status.get("dnd_enabled")),
            end_ts=float(status.get("next_dnd_end_ts", 0) or 0),
        )
    if kind in ("reaction_added", "reaction_removed"):
        item = data.get("item", {})
        return ReactionUpdated(
            channel_id=item.get("channel", ""),
            ts=item.get("ts", ""),
            emoji=data.get("reaction", ""),
            user_id=data.get("user", ""),
            added=kind == "reaction_added",
        )
    if kind and kind.startswith("channel_section"):  # created/updated/deleted/channels_*
        return SectionsChanged()
    if kind == "message" and data.get("subtype") == "message_changed":
        edited = data.get("message", {})
        return MessageEdited(
            channel_id=data.get("channel", ""),
            ts=edited.get("ts", ""),
            text=edited.get("text", ""),
        )
    if kind == "message" and data.get("subtype") == "message_deleted":
        return MessageDeleted(
            channel_id=data.get("channel", ""),
            ts=data.get("deleted_ts", ""),
        )
    if kind == "message" and not data.get("subtype"):
        return NewMessage(
            channel_id=data.get("channel", ""),
            message=RemoteMessage(
                ts=data.get("ts", ""),
                user_id=data.get("user", ""),
                text=data.get("text", ""),
                thread_ts=data.get("thread_ts", ""),
                raw_json=json.dumps(data),
            ),
        )
    return None


class HttpSlackClient:
    def __init__(self, token: Token, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.team_id = token.team_id
        self.team_name = token.team_name
        self.self_user_id = ""  # populated from auth.test at startup
        self._http = httpx.AsyncClient(
            base_url=f"https://{token.team_domain}.slack.com/api/",
            headers={"Authorization": f"Bearer {token.access_token}"},
            cookies={"d": token.cookie},
            transport=transport,
            timeout=30.0,
        )
        self._events: asyncio.Queue[Event] = asyncio.Queue()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_bytes(self, url: str) -> bytes:
        """GET an (absolute) URL with the workspace's auth — for url_private files."""
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.content

    async def _call(self, method: str, **params) -> dict:
        resp = await self._http.post(method, data=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok", False):
            err = data.get("error", "unknown_error")
            if err in _AUTH_ERRORS:
                raise AuthError(err)
            raise SlackError(err)
        return data

    async def list_channels(self) -> list[RemoteChannel]:
        data = await self._call(
            "conversations.list",
            types="public_channel,private_channel,im,mpim",
            limit=1000,
        )
        return [
            RemoteChannel(id=c["id"], name=c.get("name", ""), type=_channel_type(c))
            for c in data.get("channels", [])
        ]

    async def history(
        self, channel_id: str, limit: int = 50, oldest: str = ""
    ) -> list[RemoteMessage]:
        params = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest  # only messages newer than this ts
        data = await self._call("conversations.history", **params)
        messages = [_message_from_dict(m) for m in data.get("messages", [])]
        messages.sort(key=lambda m: float(m.ts or 0))
        return messages

    async def thread_replies(self, channel_id: str, thread_ts: str) -> list[RemoteMessage]:
        data = await self._call(
            "conversations.replies", channel=channel_id, ts=thread_ts, limit=200
        )
        messages = [_message_from_dict(m) for m in data.get("messages", [])]
        messages.sort(key=lambda m: float(m.ts or 0))
        return messages

    async def post_message(
        self, channel_id: str, text: str, thread_ts: str = ""
    ) -> RemoteMessage:
        params = {"channel": channel_id, "text": text}
        if thread_ts:
            params["thread_ts"] = thread_ts
        data = await self._call("chat.postMessage", **params)
        posted = data.get("message", {})
        return RemoteMessage(
            ts=data.get("ts", posted.get("ts", "")),
            user_id=posted.get("user", ""),
            text=posted.get("text", text),
            raw_json=json.dumps(posted),
        )

    async def add_reaction(self, channel_id: str, ts: str, emoji: str) -> None:
        await self._call("reactions.add", channel=channel_id, timestamp=ts, name=emoji)

    async def remove_reaction(self, channel_id: str, ts: str, emoji: str) -> None:
        await self._call("reactions.remove", channel=channel_id, timestamp=ts, name=emoji)

    async def mark(self, channel_id: str, ts: str) -> None:
        await self._call("conversations.mark", channel=channel_id, ts=ts)

    async def update_message(self, channel_id: str, ts: str, text: str) -> None:
        await self._call("chat.update", channel=channel_id, ts=ts, text=text)

    async def delete_message(self, channel_id: str, ts: str) -> None:
        await self._call("chat.delete", channel=channel_id, ts=ts)

    async def list_channel_sections(self) -> list[RemoteSection]:
        data = await self._call("users.channelSections.list")
        out: list[RemoteSection] = []
        for s in data.get("channel_sections", []):
            out.append(
                RemoteSection(
                    id=s.get("channel_section_id", ""),
                    name=s.get("name", ""),
                    type=s.get("type", "standard"),
                    emoji=s.get("emoji", "") or "",
                    next_id=s.get("next_channel_section_id", "") or "",
                    channel_ids=list(
                        s.get("channel_ids_page", {}).get("channel_ids", [])
                        or s.get("channel_ids", [])
                    ),
                )
            )
        return out

    async def open_conversation(self, user_ids: list[str]) -> RemoteChannel:
        data = await self._call("conversations.open", users=",".join(user_ids))
        ch = data.get("channel", {})
        ctype = "dm" if len(user_ids) == 1 else "group_dm"
        return RemoteChannel(ch.get("id", ""), ch.get("name", ""), ctype)

    async def list_thread_subscriptions(self) -> list[ThreadSub]:
        """Forward-cursor paginate ``subscriptions.thread.list`` (cap 1000)."""
        subs: list[ThreadSub] = []
        cursor = ""
        while len(subs) < 1000:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = await self._call("subscriptions.thread.list", **params)
            for t in data.get("threads", []):
                root = t.get("root_msg", {})
                subs.append(
                    ThreadSub(
                        channel_id=root.get("channel", ""),
                        thread_ts=root.get("ts", ""),
                        last_read=t.get("last_read", ""),
                    )
                )
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return subs

    async def search(self, query: str) -> list[SearchResult]:
        data = await self._call("search.messages", query=query, count=50)
        matches = data.get("messages", {}).get("matches", [])
        return [
            SearchResult(
                channel_id=m.get("channel", {}).get("id", ""),
                channel_name=m.get("channel", {}).get("name", ""),
                ts=m.get("ts", ""),
                user_id=m.get("user", ""),
                text=m.get("text", ""),
            )
            for m in matches
        ]

    async def list_custom_emoji(self) -> dict[str, str]:
        data = await self._call("emoji.list")
        return dict(data.get("emoji", {}))

    async def set_presence(self, presence: str) -> None:
        await self._call("users.setPresence", presence=presence)

    async def set_snooze(self, minutes: int) -> None:
        await self._call("dnd.setSnooze", num_minutes=minutes)

    async def end_dnd(self) -> None:
        await self._call("dnd.endSnooze")

    async def list_users(self) -> list[RemoteUser]:
        data = await self._call("users.list", limit=1000)
        return [_user_from_member(m) for m in data.get("members", [])]

    async def user_info(self, user_id: str) -> RemoteUser | None:
        try:
            data = await self._call("users.info", user=user_id)
        except SlackError:
            return None
        member = data.get("user")
        return _user_from_member(member) if member else None

    async def next_event(self) -> Event:
        return await self._events.get()

    async def _connect_once(self) -> None:
        """One RTM session: connect, pump frames, return when it drops.

        ``websockets`` is imported lazily so the Web API path needs no websocket
        dependency at import time.
        """
        import websockets

        data = await self._call("rtm.connect")
        async with websockets.connect(data["url"]) as ws:
            await self._events.put(Connected(team_id=self.team_id))
            async for raw in ws:
                event = parse_rtm_event(json.loads(raw))
                if event is not None:
                    await self._events.put(event)

    async def start_realtime(self) -> None:
        """Maintain the RTM connection with exponential-backoff reconnection."""
        import asyncio

        from slak.services import reconnect_loop

        await reconnect_loop(self._connect_once, asyncio.sleep)
