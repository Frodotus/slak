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

"""Keyboard-help content for the F1 modal.

Pure (no Textual import) so it is unit-testable. Only shortcuts that are
actually wired today are listed here — keep this honest as features land.
"""

from __future__ import annotations

from slak.version import version_line

# (section title, [(keys, description), ...])
KEYBINDINGS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Global",
        [
            ("Ctrl+P", "Command palette (all actions)"),
            ("Ctrl+K", "Jump to channel / DM"),
            ("Alt+1…9", "Switch workspace"),
            ("Ctrl+W", "Workspace switcher (filterable)"),
            ("Alt+← / Alt+→", "Channel history back / forward"),
            ("Ctrl+F", "Find in channel"),
            ("Ctrl+Shift+F", "Find in workspace"),
            ("Ctrl+T", "Toggle thread panel"),
            ("Ctrl+B", "Toggle sidebar"),
            ("Tab / Shift+Tab", "Cycle focus"),
            ("Esc", "Dismiss overlay / return to compose"),
            ("F1", "This help"),
        ],
    ),
    (
        "Compose (focused on launch)",
        [
            ("type", "Just start typing your message"),
            ("Enter", "Send"),
            ("Shift+Enter", "Newline"),
            ("@ / :", "Mention / emoji autocomplete"),
        ],
    ),
    (
        "Messages",
        [
            ("↑ / ↓", "Select previous / next message"),
            ("Enter", "Open thread"),
            ("Ctrl+R", "Add reaction"),
        ],
    ),
]

_KEY_WIDTH = 18


def render_help() -> str:
    """Rich markup for the help modal body, ending with the version footer."""
    lines = ["[b]slak — keyboard shortcuts[/b]", ""]
    for title, rows in KEYBINDINGS:
        lines.append(f"[b]{title}[/b]")
        for keys, desc in rows:
            lines.append(f"  [b]{keys:<{_KEY_WIDTH}}[/b][dim]{desc}[/dim]")
        lines.append("")
    lines.append(f"[dim]{version_line()}[/dim]")
    return "\n".join(lines)
