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

import asyncio
import json

from textual.widgets import Input

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage, RemoteUser
from slak.workspace import WorkspaceRouter


def make_app(config: Config | None = None) -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "U2", "hello there")]},
        users=[RemoteUser("U2", "bob")],
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=config or Config(),
    )


async def test_snapshot_reflects_active_channel_and_messages():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        snap = app.mcp_snapshot()
        assert snap["workspace"] == "Acme"
        assert snap["channel"]["name"] == "general"
        assert snap["recent_messages"][-1]["text"] == "hello there"
        assert snap["recent_messages"][-1]["user"] == "bob"
        assert snap["thread"] == {"open": False}


async def test_set_draft_populates_the_compose_box():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        result = app.mcp_set_draft("drafted by AI")
        assert result == {"target": "channel", "channel": "C1", "ok": True}
        assert app.query_one("#compose", Input).value == "drafted by AI"


async def test_adapter_request_relays_to_tui(tmp_path):
    from slak.mcp.adapter import request

    sock = tmp_path / "mcp.sock"
    cfg = Config.loads(f'[mcp]\nenabled = true\nsocket_path = "{sock}"\n')
    app = make_app(cfg)
    async with app.run_test() as pilot:
        for _ in range(6):
            await pilot.pause()
        snap = await request(str(sock), "get_context")
        assert snap["workspace"] == "Acme"
        drafted = await request(str(sock), "set_draft", {"text": "hi"})
        assert drafted["ok"] is True


async def test_adapter_request_when_not_running(tmp_path):
    from slak.mcp.adapter import request

    resp = await request(str(tmp_path / "absent.sock"), "get_context")
    assert "error" in resp


async def test_socket_round_trip_get_context(tmp_path):
    sock = tmp_path / "mcp.sock"
    cfg = Config.loads(f'[mcp]\nenabled = true\nsocket_path = "{sock}"\n')
    app = make_app(cfg)
    async with app.run_test() as pilot:
        for _ in range(6):
            await pilot.pause()
        assert sock.exists()
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write((json.dumps({"id": 1, "method": "get_context"}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2)
        writer.close()
        resp = json.loads(line)
        assert resp["id"] == 1
        assert resp["result"]["workspace"] == "Acme"
