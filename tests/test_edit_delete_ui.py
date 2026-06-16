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

from textual.widgets import Input

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage
from slak.ui.widgets import EditModal, MessagePane
from slak.workspace import WorkspaceRouter


def make_app(author: str = "Uself"):
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[RemoteChannel("C1", "general")],
        history={"C1": [RemoteMessage("100.0", author, "original text")]},
    )
    app = PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config(),
    )
    return app, client


async def test_ctrl_e_opens_edit_modal_prefilled_for_own_message():
    app, _ = make_app(author="Uself")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+e")
        for _ in range(3):
            await pilot.pause()
        assert isinstance(app.screen, EditModal)
        assert app.screen.query_one("#edit-input", Input).value == "original text"


async def test_editing_updates_message_text():
    app, client = make_app(author="Uself")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+e")
        for _ in range(3):
            await pilot.pause()
        app.screen.query_one("#edit-input", Input).value = "updated text"
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert (await client.history("C1"))[-1].text == "updated text"
        pane = app.query_one("#messages", MessagePane)
        assert pane._messages[-1].text == "updated text"


async def test_cannot_edit_someone_elses_message():
    app, _ = make_app(author="Uother")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert not isinstance(app.screen, EditModal)


async def test_delete_removes_message():
    app, client = make_app(author="Uself")
    async with app.run_test() as pilot:
        for _ in range(3):
            await pilot.pause()
        app.action_delete_message()
        for _ in range(4):
            await pilot.pause()
        assert await client.history("C1") == []
        pane = app.query_one("#messages", MessagePane)
        assert pane._messages == []
