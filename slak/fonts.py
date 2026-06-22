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

"""Decide whether to use the Nerd padlock glyph for private channels.

A terminal never tells an app its font, so we ask the next best thing via
fontconfig: does *any* installed font actually cover the padlock codepoint
(U+F023)? If so the terminal will render it (Nerd Fonts and FontAwesome both
include it) rather than showing tofu. This is far more reliable than matching
"Nerd Font" in family names. A config override (``[appearance] nerd_font =
auto|on|off``) wins over detection.
"""

from __future__ import annotations

import functools
import subprocess

PADLOCK_CODEPOINT = 0xF023  # Nerd Font / FontAwesome lock glyph
FILE_ICON_CODEPOINT = 0xF1C1  # FontAwesome file-pdf — representative of the file-* range


def fonts_covering(codepoint: int) -> list[str]:
    """Installed font families that cover ``codepoint`` (via fontconfig)."""
    try:
        out = subprocess.run(
            ["fc-list", f":charset={codepoint:04x}", "family"],
            capture_output=True, text=True, timeout=2,
        )
        return [ln for ln in out.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


@functools.cache
def _system_covers_padlock() -> bool:
    return bool(fonts_covering(PADLOCK_CODEPOINT))


@functools.cache
def _system_covers_file_icons() -> bool:
    return bool(fonts_covering(FILE_ICON_CODEPOINT))


def file_glyphs_available(coverer=None) -> bool:
    """True if a font covers the file-type glyph range (so attachment icons render
    instead of tofu). The padlock can be present while these aren't — check it
    separately."""
    if coverer is None:
        return _system_covers_file_icons()
    return bool(coverer(FILE_ICON_CODEPOINT))


def nerd_glyph_available(coverer=None) -> bool:
    """True if some installed font covers the padlock glyph (so it will render).

    ``coverer(codepoint) -> list[str]`` is injectable for tests; the default
    system check is cached (one ``fc-list`` per process)."""
    if coverer is None:
        return _system_covers_padlock()
    return bool(coverer(PADLOCK_CODEPOINT))


def use_nerd_glyphs(config_value, coverer=None) -> bool:
    """Resolve the Nerd-glyph decision. ``True``/``False`` force it; ``None`` (auto,
    i.e. the setting is unset) detects from installed fonts. Legacy ``on``/``off``/
    ``auto`` strings are still accepted."""
    if config_value is True or config_value == "on":
        return True
    if config_value is False or config_value == "off":
        return False
    return nerd_glyph_available(coverer)  # None / "auto"
