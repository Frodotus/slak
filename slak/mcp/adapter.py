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

"""``slak mcp`` — the stdio MCP adapter (spec 06 §4).

A thin subprocess: an AI client speaks MCP over stdio to this adapter, which
relays each call over the unix socket to the running TUI. The socket client
half (:func:`request`) is plain newline-JSON; the stdio/JSON-RPC half uses the
official ``mcp`` SDK (an optional dependency — ``pip install mcp``).
"""

from __future__ import annotations

import asyncio
import json
import sys

_NOT_RUNNING = {"error": "slak is not running or MCP is disabled"}


async def request(socket_path: str, method: str, params: dict | None = None) -> dict:
    """Send one newline-JSON request to the TUI socket and read the response."""
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except (OSError, ConnectionError):
        return dict(_NOT_RUNNING)
    try:
        writer.write(
            (json.dumps({"id": 1, "method": method, "params": params or {}}) + "\n").encode()
        )
        await writer.drain()
        line = await reader.readline()
    finally:
        writer.close()
    if not line:
        return dict(_NOT_RUNNING)
    resp = json.loads(line)
    return resp.get("result", resp)


def run_adapter(socket_path: str) -> None:
    """Run the stdio MCP server, relaying tools to the TUI socket."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "The MCP adapter needs the 'mcp' package. Install it with: pip install mcp",
            file=sys.stderr,
        )
        raise SystemExit(1)

    server = FastMCP("slak")

    @server.tool()
    async def slak_get_context() -> dict:
        """Read slak's current context (workspace, channel, selection, thread).

        ``selected_block`` is the full burst of consecutive messages the selected
        one belongs to — treat that as the message to reply to, since people
        often split a single thought across several lines.
        ``context_around_selected`` is the surrounding conversation centred on the
        selection. ``recent_messages`` is the channel tail."""
        return await request(socket_path, "get_context")

    @server.tool()
    async def slak_set_draft(text: str) -> dict:
        """Draft a reply into slak's active composer. Draft-only — never sends."""
        return await request(socket_path, "set_draft", {"text": text})

    server.run()
