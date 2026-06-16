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

from types import SimpleNamespace

from slak.config import Config, WorkspaceConfig
from slak.sections import layout

CONFIG = """
[sections.Engineering]
patterns = ["eng-*", "platform"]

[sections.Social]
patterns = ["random", "fun-*"]
"""


def ch(name):
    return SimpleNamespace(id=name, name=name, type="channel")


def test_match_section_uses_globs():
    cfg = Config.loads(CONFIG)
    assert cfg.match_section("T1", "eng-web") == "Engineering"
    assert cfg.match_section("T1", "platform") == "Engineering"
    assert cfg.match_section("T1", "random") == "Social"
    assert cfg.match_section("T1", "general") is None


def test_match_section_is_accent_and_case_insensitive():
    cfg = Config.loads('[sections.Cafe]\npatterns = ["cafe-*"]\n')
    assert cfg.match_section("T1", "Café-Crew") == "Cafe"


def test_per_workspace_sections_fully_replace_global():
    cfg = Config(
        sections={"Global": ["*"]},
        workspaces=[
            WorkspaceConfig(slug="acme", team_id="T1", sections={"Eng": ["eng-*"]})
        ],
    )
    assert cfg.match_section("T1", "eng-x") == "Eng"
    assert cfg.match_section("T1", "random") is None  # global not merged
    assert cfg.match_section("T2", "random") == "Global"  # other ws uses global


def test_sections_round_trip_through_dumps():
    cfg = Config.loads(CONFIG)
    out = Config.loads(cfg.dumps())
    assert out.match_section("T1", "eng-web") == "Engineering"


def test_layout_groups_in_section_order_with_ungrouped_last():
    names = ["Engineering", "Social"]
    def match(n):
        return {"eng-web": "Engineering", "random": "Social"}.get(n)

    channels = [ch("general"), ch("random"), ch("eng-web")]
    result = layout(names, match, channels)
    assert [name for name, _ in result] == ["Engineering", "Social", None]
    assert [c.name for c in result[0][1]] == ["eng-web"]
    assert [c.name for c in result[2][1]] == ["general"]  # ungrouped bucket


def test_layout_skips_empty_sections():
    names = ["Engineering", "Social"]
    result = layout(names, lambda n: "Engineering", [ch("eng-1"), ch("eng-2")])
    assert [name for name, _ in result] == ["Engineering"]  # Social empty, dropped
