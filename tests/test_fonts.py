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

from slak.fonts import (
    FILE_ICON_CODEPOINT,
    PADLOCK_CODEPOINT,
    file_glyphs_available,
    nerd_glyph_available,
    use_nerd_glyphs,
)


def test_nerd_glyph_available_checks_codepoint_coverage():
    covered = lambda cp: ["FontAwesome"]      # noqa: E731  a font covers U+F023
    uncovered = lambda cp: []                 # noqa: E731  nothing covers it
    assert nerd_glyph_available(covered) is True
    assert nerd_glyph_available(uncovered) is False


def test_file_glyphs_checked_separately_from_padlock():
    # a font with the padlock but NOT the file-* range (the real-world tofu case)
    padlock_only = lambda cp: ["FontAwesome"] if cp == PADLOCK_CODEPOINT else []  # noqa: E731
    assert nerd_glyph_available(padlock_only) is True       # padlock present
    assert file_glyphs_available(padlock_only) is False     # file icons are NOT
    both = lambda cp: ["NerdFont"]                          # noqa: E731
    assert file_glyphs_available(both) is True
    assert FILE_ICON_CODEPOINT != PADLOCK_CODEPOINT


def test_use_nerd_glyphs_respects_config_override():
    none = lambda cp: []                      # noqa: E731
    has = lambda cp: ["FontAwesome"]          # noqa: E731
    assert use_nerd_glyphs("on", none) is True       # forced on
    assert use_nerd_glyphs("off", has) is False      # forced off
    assert use_nerd_glyphs("auto", has) is True      # auto + glyph available
    assert use_nerd_glyphs("auto", none) is False    # auto + glyph missing
