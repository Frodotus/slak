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

"""Block Kit & legacy-attachment rendering (spec 05 §5).

Renders bot/app message structure (``blocks`` / ``attachments`` parsed from the
message's ``raw_json``) to Rich-markup lines, instead of dropping it. Interactive
controls render as muted, non-interactive labels; if any are present a single
``↗ open in Slack to interact`` line is appended. Inline block images are shown
as a labelled placeholder for now (the §4 image pipeline is messages-only).
"""

from __future__ import annotations

import json
from typing import Callable

from rich.markup import escape

from slak.render import render_message

NameOf = Callable[[str], str]
CustomRender = Callable[[str], "str | None"] | None

_RULE = "─" * 40
_ATTACH_COLORS = {"good": "green", "warning": "yellow", "danger": "red"}


def render_extras(
    raw_json: str, name_of: NameOf, custom_render: CustomRender = None
) -> list[str]:
    """Rendered lines for a message's ``blocks`` + legacy ``attachments`` (or [])."""
    try:
        data = json.loads(raw_json) if raw_json else {}
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    lines: list[str] = []
    interactive = False
    blocks = data.get("blocks") or []
    if isinstance(blocks, list):
        block_lines, block_interactive = _render_blocks(blocks, name_of, custom_render)
        lines += block_lines
        interactive = interactive or block_interactive

    attachments = data.get("attachments") or []
    if isinstance(attachments, list):
        lines += _render_attachments(attachments, name_of, custom_render)

    if interactive:
        lines.append("[dim]↗ open in Slack to interact[/dim]")
    return lines


def _text(field: dict, name_of: NameOf, custom_render: CustomRender) -> str:
    body = field.get("text", "") if isinstance(field, dict) else str(field)
    if isinstance(field, dict) and field.get("type") == "mrkdwn":
        return render_message(body, name_of, custom_render)
    return escape(body)


def _control_label(elem: dict) -> str:
    typ = elem.get("type", "")
    if typ == "button":
        return elem.get("text", {}).get("text", "Button")
    if typ == "overflow":
        return "⋯"
    if typ == "datepicker":
        return elem.get("placeholder", {}).get("text", "Pick a date")
    if typ.endswith("select"):
        return elem.get("placeholder", {}).get("text", "Select…")
    return typ or "control"


def _accessory(acc: dict) -> str:
    if acc.get("type") == "image":
        return f"🖼 {escape(acc.get('alt_text', 'image'))}"
    return f"[{escape(_control_label(acc))}]"


def _render_blocks(
    blocks: list, name_of: NameOf, custom_render: CustomRender
) -> tuple[list[str], bool]:
    lines: list[str] = []
    interactive = False
    for b in blocks:
        if not isinstance(b, dict):
            continue
        typ = b.get("type")
        if typ == "rich_text":
            # The standard block on normal messages; its content is already in
            # the message's `text` field, so rendering it would duplicate (and
            # spam "[unsupported block]"). Covered by text — emit nothing.
            continue
        if typ == "header":
            lines.append(f"[b]{escape(b.get('text', {}).get('text', ''))}[/]")
        elif typ == "section":
            if "text" in b:
                lines.append(_text(b["text"], name_of, custom_render))
            fields = b.get("fields", [])
            for i in range(0, len(fields), 2):
                cells = [_text(f, name_of, custom_render) for f in fields[i : i + 2]]
                lines.append("    ".join(cells))
            if "accessory" in b:
                lines.append(f"[dim]{_accessory(b['accessory'])}[/dim]")
                if b["accessory"].get("type") != "image":
                    interactive = True
        elif typ == "context":
            parts = []
            for e in b.get("elements", []):
                if e.get("type") == "image":
                    parts.append(f"🖼 {escape(e.get('alt_text', 'image'))}")
                else:
                    parts.append(_text(e, name_of, custom_render))
            lines.append(f"[dim]{'  '.join(parts)}[/dim]")
        elif typ == "divider":
            lines.append(f"[dim]{_RULE}[/dim]")
        elif typ == "image":
            label = b.get("title", {}).get("text") or b.get("alt_text", "image")
            lines.append(f"[dim]🖼 {escape(label)}[/dim]")
        elif typ == "actions":
            labels = [_control_label(e) for e in b.get("elements", [])]
            lines.append("  ".join(f"[dim]\\[{escape(x)}][/dim]" for x in labels))
            interactive = True
        else:
            lines.append(f"[dim]\\[unsupported block: {escape(str(typ))}][/dim]")
    return lines, interactive


def _render_attachments(
    attachments: list, name_of: NameOf, custom_render: CustomRender
) -> list[str]:
    lines: list[str] = []
    for a in attachments:
        if not isinstance(a, dict):
            continue
        color = a.get("color", "")
        rich_color = _ATTACH_COLORS.get(color, color if color.startswith("#") else "")
        bar = f"[{rich_color}]▎[/]" if rich_color else "▎"
        if a.get("pretext"):
            lines.append(render_message(a["pretext"], name_of, custom_render))
        if a.get("title"):
            lines.append(f"{bar} [b]{escape(a['title'])}[/]")
        if a.get("text"):
            lines.append(f"{bar} {render_message(a['text'], name_of, custom_render)}")
        fields = a.get("fields", [])
        for i in range(0, len(fields), 2):
            cells = [
                f"[b]{escape(f.get('title', ''))}[/] {escape(f.get('value', ''))}"
                for f in fields[i : i + 2]
            ]
            lines.append(f"{bar} " + "    ".join(cells))
        if a.get("footer"):
            lines.append(f"[dim]{escape(a['footer'])}[/dim]")
    return lines
