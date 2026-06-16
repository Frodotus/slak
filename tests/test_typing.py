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

import time

from textual.widgets import Static

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage, RemoteUser, Typing
from slak.slack.http import parse_rtm_event
from slak.workspace import WorkspaceRouter


def test_parse_user_typing():
    e = parse_rtm_event({"type": "user_typing", "channel": "C1", "user": "U2"})
    assert isinstance(e, Typing)
    assert (e.channel_id, e.user_id) == ("C1", "U2")


def make_app() -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general"), RemoteChannel("C2", "random")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
        users=[RemoteUser("U2", "alice")],
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )


async def test_typing_indicator_shows_for_active_channel():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app.client.emit_event(Typing("C1", "U2"))
        await pilot.pause()
        typing = app.query_one("#typing", Static)
        assert typing.display is True
        assert "U2" in app._typing
        assert app._name_of("U2") == "alice"  # resolved display name is shown


async def test_typing_ignores_other_channel_and_self():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app.client.emit_event(Typing("C2", "U2"))     # not the active channel
        await app.client.emit_event(Typing("C1", "Uself"))  # ourselves
        await pilot.pause()
        assert app._typing == {}
        assert app.query_one("#typing", Static).display is False


async def test_prune_removes_expired_typers():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app._typing["U2"] = time.monotonic() - 1  # already expired
        app._prune_typing()
        assert app._typing == {}
        assert app.query_one("#typing", Static).display is False


async def test_typing_into_compose_sends_throttled_user_typing():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await pilot.press("h")
        for _ in range(2):
            await pilot.pause()
        assert app.client.typing_sent == ["C1"]
        await pilot.press("i")  # immediate second keystroke -> throttled
        for _ in range(2):
            await pilot.pause()
        assert app.client.typing_sent == ["C1"]  # still one


async def test_no_outbound_typing_when_disabled():
    client = FakeSlackClient(
        team_id="T1", team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("1.0", "u", "hi")]},
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config.loads("[general]\ntyping_indicators = false\n"),
    )
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await pilot.press("h")
        for _ in range(2):
            await pilot.pause()
        assert app.client.typing_sent == []
