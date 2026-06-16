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

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import Connected, FakeSlackClient, RemoteChannel, RemoteMessage
from slak.workspace import WorkspaceRouter


def make_app():
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", "alice", "hello")]},
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    return app, client


async def test_backfill_pulls_messages_missed_while_disconnected():
    app, client = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        # a message arrives "while disconnected" — only in the server, not cache
        client._history["C1"].append(RemoteMessage("200.0", "bob", "while away"))

        await app._backfill_now(client)
        for _ in range(2):
            await pilot.pause()

        texts = [m.text for m in app.cache.get_messages("C1")]
        assert "while away" in texts


async def test_reconnect_event_triggers_backfill():
    app, client = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app._last_backfill.clear()  # ensure not deduped
        client._history["C1"].append(RemoteMessage("300.0", "carol", "reconnect msg"))

        await client.emit_event(Connected(team_id="T1"))
        for _ in range(5):
            await pilot.pause()

        texts = [m.text for m in app.cache.get_messages("C1")]
        assert "reconnect msg" in texts
