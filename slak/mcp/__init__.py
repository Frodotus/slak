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

"""Embedded MCP server — TUI-side core (spec 06 §4).

slak exposes a read-only context snapshot and a draft-only writer so an external
AI client can read what you're looking at and draft a reply into the composer.
This module holds the pure, testable pieces: the snapshot builder and the
newline-JSON request handler. The unix-socket server lives in the app; the stdio
``slak mcp`` adapter (official ``mcp`` SDK) lives in :mod:`slak.mcp.adapter`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable


def default_socket_path() -> str:
    return str(Path.home() / ".local" / "share" / "slak" / "mcp.sock")


def message_dict(rm, name_of: Callable[[str], str]) -> dict:
    """A snapshot message: display name + rendered text + reaction summary."""
    return {
        "ts": rm.ts,
        "user": name_of(rm.user_id),
        "text": rm.text,
        "reactions": [{"emoji": r.emoji, "count": r.count} for r in rm.reactions],
    }


def build_snapshot(*, workspace, channel, selected, thread, recent) -> dict:
    """Assemble the immutable context snapshot (all names are display names)."""
    return {
        "workspace": workspace,
        "channel": channel,
        "selected_message": selected,
        "thread": thread or {"open": False},
        "recent_messages": recent,
    }


def handle_request(
    line: str,
    get_snapshot: Callable[[], dict],
    set_draft: Callable[[str], dict],
) -> dict:
    """Process one newline-JSON request into a response dict.

    ``{"id", "method": "get_context"|"set_draft", "params": {...}}`` →
    ``{"id", "result"}`` or ``{"id", "error"}``.
    """
    try:
        req = json.loads(line)
    except (ValueError, TypeError):
        return {"error": "invalid json"}
    rid = req.get("id")
    method = req.get("method")
    if method == "get_context":
        return {"id": rid, "result": get_snapshot()}
    if method == "set_draft":
        text = (req.get("params") or {}).get("text", "")
        return {"id": rid, "result": set_draft(text)}
    return {"id": rid, "error": f"unknown method: {method}"}


async def serve(socket_path: str, get_snapshot, set_draft, *, on_ready=None):
    """Run the newline-JSON unix-socket server until cancelled.

    Each connection is handled line-by-line through :func:`handle_request`. The
    socket file is created mode ``0600`` and removed on shutdown.
    """
    import asyncio

    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    async def on_conn(reader, writer):
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                resp = handle_request(line.decode(), get_snapshot, set_draft)
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(on_conn, path=str(path))
    os.chmod(path, 0o600)
    if on_ready is not None:
        on_ready()
    try:
        async with server:
            await server.serve_forever()
    finally:
        if path.exists():
            path.unlink()
