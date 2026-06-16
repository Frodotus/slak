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

from slak.help import render_help
from slak.version import __version__, version_line


def test_version_line_includes_version_and_tos_warning():
    line = version_line()
    assert __version__ in line
    assert "unofficial" in line.lower()


def test_help_lists_core_shortcuts():
    text = render_help()
    for key in ("Ctrl+P", "Ctrl+K", "Ctrl+R", "Enter", "F1"):
        assert key in text


def test_help_groups_have_headings():
    text = render_help()
    for heading in ("Global", "Compose", "Messages"):
        assert heading in text


def test_help_includes_version_footer():
    assert __version__ in render_help()
