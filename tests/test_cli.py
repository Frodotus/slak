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

from slak.__main__ import choose_active, startup_mode
from slak.config import Config, WorkspaceConfig
from slak.slack import Token


def _tok(team_id):
    return Token(access_token="x", cookie="c", team_id=team_id, team_name=team_id)


def test_resolve_file_icon_style():
    from slak.app import resolve_file_icon_style
    assert resolve_file_icon_style("nerd", False) is True     # forced on
    assert resolve_file_icon_style("emoji", True) is False    # forced off
    assert resolve_file_icon_style("auto", True) is True      # follows detection
    assert resolve_file_icon_style("auto", False) is False


def test_choose_active_prefers_last_used_workspace():
    tokens = [_tok("T1"), _tok("T2"), _tok("T3")]
    assert choose_active(tokens, Config(last_workspace="T2")) == "T2"


def test_choose_active_falls_back_to_default_then_first():
    tokens = [_tok("T1"), _tok("T2")]
    # stale last_workspace (not present) -> configured default
    cfg = Config(last_workspace="GONE",
                 default_workspace="beta",
                 workspaces=[WorkspaceConfig(slug="beta", team_id="T2")])
    assert choose_active(tokens, cfg) == "T2"
    # nothing remembered or configured -> first token
    assert choose_active(tokens, Config()) == "T1"


def test_demo_flag_always_wins():
    assert startup_mode(has_tokens=True, demo=True, interactive=True) == "demo"
    assert startup_mode(has_tokens=False, demo=True, interactive=False) == "demo"


def test_tokens_run_the_real_workspace_by_default():
    assert startup_mode(has_tokens=True, demo=False, interactive=True) == "real"
    assert startup_mode(has_tokens=True, demo=False, interactive=False) == "real"


def test_first_run_interactive_opens_the_wizard():
    assert startup_mode(has_tokens=False, demo=False, interactive=True) == "wizard"


def test_no_token_non_interactive_reports_instead_of_demo():
    # e.g. CI/cron with no token and no --demo -> exit with instructions, never demo
    assert startup_mode(has_tokens=False, demo=False, interactive=False) == "no-token"
