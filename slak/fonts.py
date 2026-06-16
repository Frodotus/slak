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

"""Nerd Font detection — pick Nerd glyphs (single-width padlock, …) when available.

A terminal never tells an app which font it renders with, so this is a heuristic:
is a Nerd Font *installed* on the system (via ``fc-list``)? Combined with a config
override (``[appearance] nerd_font = auto|on|off``) it decides whether to use Nerd
glyphs or a broadly-supported fallback.
"""

from __future__ import annotations

import functools
import subprocess


def list_system_fonts() -> list[str]:
    """Installed font family names (via fontconfig); empty if unavailable."""
    try:
        out = subprocess.run(
            ["fc-list", ":", "family"],
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


@functools.cache
def _system_has_nerd_font() -> bool:
    return any("nerd font" in f.lower() for f in list_system_fonts())


def nerd_font_available(lister=None) -> bool:
    """True if a Nerd Font is installed. ``lister`` is injectable for tests; the
    default system check is cached (one ``fc-list`` per process)."""
    if lister is None:
        return _system_has_nerd_font()
    return any("nerd font" in f.lower() for f in lister())


def use_nerd_glyphs(config_value: str, lister=None) -> bool:
    """Resolve the Nerd-glyph decision: ``on``/``off`` force it, ``auto`` detects."""
    if config_value == "on":
        return True
    if config_value == "off":
        return False
    return nerd_font_available(lister)
