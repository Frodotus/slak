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

"""Emoji shortcode index for `:name:` autocomplete (and later, rendering).

Sourced from `emoji-data-python` (the iamcal/emoji-data set maintained by a Slack
co-founder) so every shortcode we offer is a name Slack actually accepts — avoiding
the `invalid_name` failures that CLDR-style sets (e.g. `thumbs_up`) cause on
`reactions.add`. `match` returns candidates for a typed token, prefix matches first.
"""

from __future__ import annotations

import re

import emoji_data_python as _ed

_VS16 = "️"
_SHORTCODE = re.compile(r":([a-zA-Z0-9_+\-]+):")


def _build() -> dict[str, str]:
    return {name: ec.char for name, ec in _ed.emoji_short_names.items()}


SHORTCODES: dict[str, str] = _build()


def match(token: str, limit: int = 8) -> list[tuple[str, str]]:
    """Return (name, glyph) candidates whose name contains ``token``.

    Names that start with the token rank first, then alphabetically.
    """
    t = token.lower()
    hits = [(name, glyph) for name, glyph in SHORTCODES.items() if t in name]
    hits.sort(key=lambda ng: (not ng[0].startswith(t), ng[0]))
    return hits[:limit]


def should_render_unicode(glyph: str) -> bool:
    """True if ``glyph`` is safe to render as a terminal glyph.

    Single-codepoint emoji (optionally + VS16) render with predictable width;
    multi-codepoint sequences (flags, ZWJ families, skin-tone modifiers) can
    corrupt alignment, so we keep those as ``:shortcode:`` text instead.
    """
    return len(glyph) == 1 or (len(glyph) == 2 and glyph[1] == _VS16)


def emoji_glyph(name: str) -> str:
    """Glyph for a shortcode name if known and safe, else ``:name:``."""
    glyph = SHORTCODES.get(name)
    return glyph if glyph and should_render_unicode(glyph) else f":{name}:"


def emojize(text: str) -> str:
    """Replace ``:shortcode:`` with its glyph (known + safe ones only)."""
    return _SHORTCODE.sub(lambda m: emoji_glyph(m.group(1)), text)


def resolve_custom_emoji(
    name: str, customs: dict[str, str], max_hops: int = 8
) -> str | None:
    """Resolve a custom-emoji name to its image URL, following ``alias:`` chains.

    Returns None if the name is unknown or the alias chain cycles / runs too deep.
    """
    seen: set[str] = set()
    for _ in range(max_hops):
        if name in seen:
            return None
        seen.add(name)
        value = customs.get(name)
        if value is None:
            return None
        if value.startswith("alias:"):
            name = value[len("alias:") :]
            continue
        return value
    return None
