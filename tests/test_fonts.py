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

from slak.fonts import nerd_font_available, use_nerd_glyphs


def test_nerd_font_available_detects_a_nerd_family():
    has = lambda: ["DejaVu Sans", "JetBrainsMono Nerd Font", "Noto"]  # noqa: E731
    none = lambda: ["DejaVu Sans", "Noto Sans Mono"]  # noqa: E731
    assert nerd_font_available(has) is True
    assert nerd_font_available(none) is False
    assert nerd_font_available(lambda: []) is False


def test_use_nerd_glyphs_respects_config_override():
    none = lambda: []  # noqa: E731  (no nerd font installed)
    has = lambda: ["Hack Nerd Font Mono"]  # noqa: E731
    assert use_nerd_glyphs("on", none) is True       # forced on
    assert use_nerd_glyphs("off", has) is False      # forced off
    assert use_nerd_glyphs("auto", has) is True      # auto + installed
    assert use_nerd_glyphs("auto", none) is False    # auto + missing
