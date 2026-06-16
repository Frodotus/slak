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

from slak.emoji import SHORTCODES, match


def test_shortcodes_maps_names_to_glyphs():
    assert SHORTCODES.get("rocket") == "🚀"


def test_shortcodes_includes_aliases():
    assert SHORTCODES.get("ab") == "🆎"


def test_match_finds_by_substring():
    names = [n for n, _ in match("rocket")]
    assert "rocket" in names


def test_match_ranks_prefix_first():
    names = [n for n, _ in match("roc")]
    assert names and names[0].startswith("roc")


def test_match_returns_name_and_glyph_pairs():
    name, glyph = match("rocket")[0]
    assert isinstance(name, str) and isinstance(glyph, str)


def test_match_respects_limit():
    assert len(match("a", limit=5)) <= 5


def test_should_render_unicode_simple_and_vs16():
    from slak.emoji import should_render_unicode
    assert should_render_unicode("👋") is True          # 1 codepoint
    assert should_render_unicode("❤️") is True      # base + VS16
    assert should_render_unicode("🇺🇸") is False          # 2 regional indicators (flag)
    assert should_render_unicode("👍🏽") is False          # skin-tone modifier


def test_emojize_replaces_known_safe_shortcodes():
    from slak.emoji import emojize
    assert emojize("morning :wave:") == "morning 👋"
    assert emojize(":rocket: ship") == "🚀 ship"


def test_emojize_leaves_unknown_shortcodes():
    from slak.emoji import emojize
    assert emojize("a :not_an_emoji: b") == "a :not_an_emoji: b"


def test_emojize_keeps_unsafe_emoji_as_shortcode():
    from slak.emoji import emojize
    # flags are multi-codepoint -> keep the shortcode to avoid width corruption
    assert emojize(":us:") == ":us:"


def test_resolve_custom_emoji_follows_aliases():
    from slak.emoji import resolve_custom_emoji
    customs = {"thisisfine": "https://e/fine.png", "blob": "alias:thisisfine"}
    assert resolve_custom_emoji("blob", customs) == "https://e/fine.png"
    assert resolve_custom_emoji("thisisfine", customs) == "https://e/fine.png"
    assert resolve_custom_emoji("missing", customs) is None


def test_resolve_custom_emoji_is_cycle_safe():
    from slak.emoji import resolve_custom_emoji
    assert resolve_custom_emoji("a", {"a": "alias:b", "b": "alias:a"}) is None
