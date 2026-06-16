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

from slak.slack import FakeSlackClient
from slak.workspace import WorkspaceRouter


def clients(*team_ids):
    return [FakeSlackClient(team_id=t, team_name=t) for t in team_ids]


def test_ordered_respects_given_order_filtered_to_known():
    r = WorkspaceRouter(clients("T1", "T2"), order=["T2", "T1", "TGHOST"])
    assert r.ordered() == ["T2", "T1"]


def test_active_defaults_to_first_in_order():
    r = WorkspaceRouter(clients("T1", "T2"), order=["T2", "T1"])
    assert r.active_team_id() == "T2"
    assert r.active().team_id == "T2"


def test_set_active_switches():
    r = WorkspaceRouter(clients("T1", "T2"), order=["T1", "T2"])
    assert r.set_active("T2") is True
    assert r.active_team_id() == "T2"


def test_set_active_unknown_is_rejected():
    r = WorkspaceRouter(clients("T1"), order=["T1"])
    assert r.set_active("TNOPE") is False
    assert r.active_team_id() == "T1"


def test_set_active_index_in_and_out_of_range():
    r = WorkspaceRouter(clients("T1", "T2"), order=["T1", "T2"])
    assert r.set_active_index(1) is True
    assert r.active_team_id() == "T2"
    assert r.set_active_index(9) is False
    assert r.active_team_id() == "T2"


def test_clients_in_order_and_all():
    r = WorkspaceRouter(clients("T1", "T2"), order=["T2", "T1"])
    assert [c.team_id for c in r.clients_in_order()] == ["T2", "T1"]
    assert {c.team_id for c in r.all()} == {"T1", "T2"}


def test_single_helper():
    c = FakeSlackClient(team_id="T9", team_name="Solo")
    r = WorkspaceRouter.single(c)
    assert r.ordered() == ["T9"]
    assert r.active().team_id == "T9"
