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

"""Color-theme registry — the swappable variables layer (``Ctrl+Y``, spec 05 §2).

A theme is just the set of color *slots* the base ``app.tcss`` references. The
app feeds the active theme's slots in as CSS variables (see
``PyslkApp.get_css_variables``), so switching themes restyles everything with no
restart. This ships a representative subset of the full ~70-theme set.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from slak.color import ensure_contrast

# The slots referenced by app.tcss (kept in sync with it).
SLOTS = ("accent", "bg", "hairline", "surface", "surface_dark", "text", "text_muted")

DEFAULT_THEME = "dark"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1a1b26", "surface": "#1f2233", "surface_dark": "#16161e",
        "text": "#c0caf5", "text_muted": "#565f89", "accent": "#7aa2f7",
        "hairline": "#2a2e42",
    },
    "light": {
        "bg": "#eaeaef", "surface": "#ffffff", "surface_dark": "#dcdce4",
        "text": "#2b2b3a", "text_muted": "#7c7c92", "accent": "#3b6ea8",
        "hairline": "#c8c8d4",
    },
    "dracula": {
        "bg": "#282a36", "surface": "#343746", "surface_dark": "#21222c",
        "text": "#f8f8f2", "text_muted": "#6272a4", "accent": "#bd93f9",
        "hairline": "#44475a",
    },
    "nord": {
        "bg": "#2e3440", "surface": "#3b4252", "surface_dark": "#272c36",
        "text": "#e5e9f0", "text_muted": "#7b88a1", "accent": "#88c0d0",
        "hairline": "#434c5e",
    },
    "gruvbox-dark": {
        "bg": "#282828", "surface": "#32302f", "surface_dark": "#1d2021",
        "text": "#ebdbb2", "text_muted": "#928374", "accent": "#fabd2f",
        "hairline": "#3c3836",
    },
    "solarized-dark": {
        "bg": "#002b36", "surface": "#073642", "surface_dark": "#00212b",
        "text": "#93a1a1", "text_muted": "#586e75", "accent": "#268bd2",
        "hairline": "#0a4856",
    },
    "tokyo-night": {
        "bg": "#1a1b26", "surface": "#24283b", "surface_dark": "#16161e",
        "text": "#a9b1d6", "text_muted": "#565f89", "accent": "#7aa2f7",
        "hairline": "#2a2e42",
    },
    "catppuccin-mocha": {
        "bg": "#1e1e2e", "surface": "#313244", "surface_dark": "#181825",
        "text": "#cdd6f4", "text_muted": "#7f849c", "accent": "#cba6f7",
        "hairline": "#45475a",
    },
    "one-dark": {
        "bg": "#282c34", "surface": "#31363f", "surface_dark": "#21252b",
        "text": "#abb2bf", "text_muted": "#5c6370", "accent": "#61afef",
        "hairline": "#3b4048",
    },
    "rose-pine": {
        "bg": "#191724", "surface": "#1f1d2e", "surface_dark": "#13111f",
        "text": "#e0def4", "text_muted": "#6e6a86", "accent": "#c4a7e7",
        "hairline": "#26233a",
    },
    # ANSI-palette themes follow the terminal's own 16 colours (spec 05 §ANSI):
    # the UI re-themes when the user re-themes their terminal. Exempt from the
    # CIELAB contrast rule since the actual colours are terminal-defined.
    "ansi-dark": {
        "bg": "ansi_default", "surface": "ansi_bright_black", "surface_dark": "ansi_black",
        "text": "ansi_default", "text_muted": "ansi_bright_black",
        "accent": "ansi_bright_blue", "hairline": "ansi_bright_black",
    },
    "ansi-light": {
        "bg": "ansi_default", "surface": "ansi_white", "surface_dark": "ansi_bright_white",
        "text": "ansi_default", "text_muted": "ansi_bright_black",
        "accent": "ansi_blue", "hairline": "ansi_white",
    },
}


def theme_names() -> list[str]:
    """All theme names in display order."""
    return list(THEMES)


def get_theme(name: str) -> dict[str, str]:
    """The slot table for ``name``, falling back to the default theme."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def theme_variables(name: str) -> dict[str, str]:
    """Slots as Textual CSS variables (``surface_dark`` slot → ``$surface-dark``).

    ``surface`` is contrast-adjusted against ``bg`` so the sidebar always reads as
    separate from the message pane (spec 05 §contrast).
    """
    theme = get_theme(name)
    out = {slot.replace("_", "-"): theme[slot] for slot in SLOTS}
    bg, surface = theme["bg"], theme["surface"]
    if bg.startswith("#") and surface.startswith("#"):  # ANSI themes are exempt
        out["surface"] = ensure_contrast(bg, surface)
    return out


def register_theme(name: str, slots: dict[str, str]) -> None:
    """Register/override a theme; must define every slot in :data:`SLOTS`."""
    THEMES[name] = {s: slots[s] for s in SLOTS}


def load_theme_files(directory) -> int:
    """Load user themes from ``<directory>/*.toml`` (spec 05 §custom).

    Each file's stem is the theme name (same name as a built-in overrides it);
    its keys are the slots, flat or under a ``[theme]`` table. Returns the count
    loaded; malformed/incomplete files are skipped.
    """
    d = Path(directory)
    if not d.is_dir():
        return 0
    loaded = 0
    for path in sorted(d.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, ValueError):
            continue
        slots = data.get("theme", data)
        if all(s in slots for s in SLOTS):
            register_theme(path.stem, slots)
            loaded += 1
    return loaded
