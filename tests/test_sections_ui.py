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

import pytest
from textual.css.query import NoMatches
from textual.widgets import ListItem

from slak.app import PyslkApp
from slak.cache import Cache
from slak.config import Config
from slak.slack import FakeSlackClient, RemoteChannel, RemoteMessage
from slak.ui.widgets import Sidebar
from slak.workspace import WorkspaceRouter

SECTIONED = '[sections.Engineering]\npatterns = ["eng-*"]\n'


def make_app(config_text: str = SECTIONED) -> PyslkApp:
    client = FakeSlackClient(
        team_id="T1",
        team_name="Acme",
        channels=[
            RemoteChannel("C1", "general"),
            RemoteChannel("C2", "eng-web"),
            RemoteChannel("C3", "eng-data"),
            RemoteChannel("C4", "random"),
        ],
        history={"C1": [RemoteMessage("100.0", "alice", "hi")]},
    )
    return PyslkApp(
        router=WorkspaceRouter.single(client),
        cache=Cache.open(":memory:"),
        config=Config.loads(config_text),
    )


async def test_sidebar_groups_channels_into_sections():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        assert "Engineering" in sidebar._section_ids.values()
        # eng channels and ungrouped channels are all present
        for cid in ("C2", "C3", "C1", "C4"):
            assert sidebar.get_child_by_id(cid, ListItem) is not None


async def test_collapsing_a_section_hides_its_channels():
    app = make_app()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        await app._toggle_section("Engineering")
        for _ in range(2):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        with pytest.raises(NoMatches):
            sidebar.get_child_by_id("C2", ListItem)  # eng-web hidden
        assert sidebar.get_child_by_id("C1", ListItem) is not None  # general stays


async def test_no_config_sections_renders_flat():
    app = make_app(config_text="")
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        assert sidebar._section_ids == {}
        assert sidebar.get_child_by_id("C2", ListItem) is not None
