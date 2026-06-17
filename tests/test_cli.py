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

from slak.__main__ import startup_mode


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
