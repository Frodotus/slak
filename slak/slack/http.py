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
import urllib.parse

import httpx

from slak.debuglog import debug

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

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
    StarsChanged,
    Typing,
    PresenceChanged,
    Reaction,
    ReactionUpdated,
    RemoteBot,
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
        reply_count=int(m.get("reply_count", 0)),
        username=m.get("username") or m.get("bot_profile", {}).get("name", ""),
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
        handle=m.get("name", ""),
        avatar=prof.get("image_72") or prof.get("image_48") or "",
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
    if kind in ("star_added", "star_removed"):
        return StarsChanged()
    if kind == "user_typing":
        return Typing(channel_id=data.get("channel", ""), user_id=data.get("user", ""))
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
            follow_redirects=True,  # url_private originals 302 to a CDN
        )
        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self._ws = None  # active RTM websocket (set while connected)
        self._rtm_msg_id = 0

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
        # users.conversations returns only the conversations the user has *joined*
        # (and their open DMs) — i.e. the sidebar. conversations.list would return
        # every public channel in the workspace plus closed DMs ("hidden" ones).
        channels: list[RemoteChannel] = []
        cursor = ""
        while True:
            params = dict(
                types="public_channel,private_channel,im,mpim",
                exclude_archived="true",
                limit=1000,
            )
            if cursor:
                params["cursor"] = cursor
            data = await self._call("users.conversations", **params)
            for c in data.get("channels", []):
                if c.get("is_archived"):
                    continue
                ctype = _channel_type(c)
                # drop DMs/MPDMs the user has closed (hidden from the sidebar)
                if ctype in ("dm", "group_dm") and c.get("is_open") is False:
                    continue
                channels.append(RemoteChannel(
                    id=c["id"], name=c.get("name", ""), type=ctype,
                    user=c.get("user", ""),
                    topic=c.get("topic", {}).get("value", ""),
                ))
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return channels

    async def list_all_public_channels(self) -> list[RemoteChannel]:
        # Every public channel in the workspace (joined or not) — for the finder's
        # discover-and-join. Each carries is_member so the UI/flow can tell which
        # ones still need joining.
        channels: list[RemoteChannel] = []
        cursor = ""
        while True:
            params = dict(types="public_channel", exclude_archived="true", limit=1000)
            if cursor:
                params["cursor"] = cursor
            data = await self._call("conversations.list", **params)
            for c in data.get("channels", []):
                if c.get("is_archived"):
                    continue
                channels.append(RemoteChannel(
                    id=c["id"], name=c.get("name", ""), type=_channel_type(c),
                    topic=c.get("topic", {}).get("value", ""),
                    is_member=bool(c.get("is_member", False)),
                ))
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return channels

    async def join_channel(self, channel_id: str) -> None:
        await self._call("conversations.join", channel=channel_id)

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

    async def list_unread_channels(self) -> list[str]:
        """Channel/DM ids with unread messages, via the internal client.counts."""
        data = await self._call("client.counts")
        out: list[str] = []
        for bucket in ("channels", "mpims", "ims"):
            for c in data.get(bucket, []):
                if c.get("has_unreads") and c.get("id"):
                    out.append(c["id"])
        return out

    async def list_stars(self) -> list[str]:
        data = await self._call("stars.list", count=200)
        out: list[str] = []
        for item in data.get("items", []):
            if item.get("type") in ("channel", "im", "group") and item.get("channel"):
                out.append(item["channel"])
        return out

    async def send_typing(self, channel_id: str) -> None:
        """Send an RTM ``typing`` frame (best-effort; no-op if disconnected)."""
        ws = self._ws
        if ws is None:
            return
        self._rtm_msg_id += 1
        try:
            await ws.send(json.dumps(
                {"id": self._rtm_msg_id, "type": "typing", "channel": channel_id}
            ))
        except Exception:
            pass

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

    async def bot_info(self, bot_id: str) -> RemoteBot | None:
        try:
            data = await self._call("bots.info", bot=bot_id)
        except SlackError:
            return None
        bot = data.get("bot", {})
        name = bot.get("name", "")
        if not name:
            return None
        icons = bot.get("icons") or {}
        avatar = icons.get("image_72") or icons.get("image_48") or icons.get("image_36") or ""
        return RemoteBot(name=name, avatar=avatar)

    async def next_event(self) -> Event:
        return await self._events.get()

    def _flannel_url(self) -> str:
        """Slack's internal realtime WebSocket (flannel) — the browser client's
        socket. Legacy ``rtm.connect`` is dead for xoxc tokens."""
        token = urllib.parse.quote(self.token.access_token, safe="")
        return (
            f"wss://wss-primary.slack.com/?token={token}"
            "&sync_desync=1&slack_client=desktop"
            "&start_args=%3Fagent%3Dclient%26connect_only%3Dtrue%26ms_latest%3Dtrue"
            "&no_query_on_subscribe=1&flannel=3&lazy_channels=1"
            f"&gateway_server={self.team_id}-1&batch_presence_aware=1"
        )

    async def _connect_once(self) -> None:
        """One realtime session: connect to the flannel WS, pump frames, return
        when it drops. ``websockets`` is imported lazily."""
        import websockets

        headers = [
            ("Cookie", f"d={self.token.cookie}"),
            ("Sec-Fetch-Dest", "websocket"),
        ]
        async with websockets.connect(
            self._flannel_url(),
            additional_headers=headers,
            user_agent_header=_BROWSER_UA,
            max_size=None,  # flannel's initial state frames can be large
        ) as ws:
            self._ws = ws  # expose for outbound frames (typing)
            await self._events.put(Connected(team_id=self.team_id))
            try:
                async for raw in ws:
                    data = json.loads(raw)
                    debug(
                        f"[ws] type={data.get('type')!r} "
                        f"subtype={data.get('subtype')!r} channel={data.get('channel', '')}"
                    )
                    event = parse_rtm_event(data)
                    if event is not None:
                        await self._events.put(event)
            finally:
                self._ws = None

    async def start_realtime(self) -> None:
        """Maintain the RTM connection with exponential-backoff reconnection."""
        import asyncio

        from slak.services import reconnect_loop

        await reconnect_loop(self._connect_once, asyncio.sleep)
