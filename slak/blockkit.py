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
ImageRender = Callable[[str], "str | None"] | None  # url -> placeholder markup

_RULE = "─" * 40
_ATTACH_COLORS = {"good": "green", "warning": "yellow", "danger": "red"}


def render_extras(
    raw_json: str,
    name_of: NameOf,
    custom_render: CustomRender = None,
    image_render: ImageRender = None,
) -> list[str]:
    """Rendered lines for a message's ``blocks`` + legacy ``attachments`` (or []).

    ``image_render(url)`` may return a terminal-image placeholder for an image
    that's been transmitted; when it returns ``None`` the image falls back to a
    labelled ``🖼`` placeholder.
    """
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
        block_lines, block_interactive = _render_blocks(
            blocks, name_of, custom_render, image_render
        )
        lines += block_lines
        interactive = interactive or block_interactive

    attachments = data.get("attachments") or []
    if isinstance(attachments, list):
        lines += _render_attachments(attachments, name_of, custom_render, image_render)

    for f in data.get("files") or []:
        url = _file_image_url(f)
        if url:
            lines.append(_img(url, f.get("name", "image"), image_render))

    if interactive:
        lines.append("[dim]↗ open in Slack to interact[/dim]")
    return lines


def image_urls(raw_json: str) -> list[str]:
    """All image URLs referenced by a message's blocks/attachments (in order)."""
    try:
        data = json.loads(raw_json) if raw_json else {}
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    urls: list[str] = []
    for b in data.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "image" and b.get("image_url"):
            urls.append(b["image_url"])
        acc = b.get("accessory")
        if isinstance(acc, dict) and acc.get("type") == "image" and acc.get("image_url"):
            urls.append(acc["image_url"])
        for e in b.get("elements", []) if b.get("type") == "context" else []:
            if isinstance(e, dict) and e.get("type") == "image" and e.get("image_url"):
                urls.append(e["image_url"])
    for a in data.get("attachments") or []:
        if not isinstance(a, dict):
            continue
        for key in ("image_url", "thumb_url"):
            if a.get(key):
                urls.append(a[key])
    for f in data.get("files") or []:
        url = _file_image_url(f)
        if url:
            urls.append(url)
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def _file_image_url(f) -> str | None:
    """A shareable image URL for a Slack file (thumb preferred), or None."""
    if not isinstance(f, dict) or not str(f.get("mimetype", "")).startswith("image/"):
        return None
    return f.get("thumb_360") or f.get("thumb_480") or f.get("url_private")


def _img(url: str, label: str, image_render: ImageRender) -> str:
    """A rendered inline image placeholder if ready, else a labelled fallback."""
    if image_render and url:
        markup = image_render(url)
        if markup:
            return markup
    return f"🖼 {escape(label)}"


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
    blocks: list, name_of: NameOf, custom_render: CustomRender,
    image_render: ImageRender = None,
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
            acc = b.get("accessory")
            if acc:
                if acc.get("type") == "image":
                    lines.append(
                        _img(acc.get("image_url", ""), acc.get("alt_text", "image"),
                             image_render)
                    )
                else:
                    lines.append(f"[dim][{escape(_control_label(acc))}][/dim]")
                    interactive = True
        elif typ == "context":
            parts = []
            for e in b.get("elements", []):
                if e.get("type") == "image":
                    parts.append(
                        _img(e.get("image_url", ""), e.get("alt_text", "image"),
                             image_render)
                    )
                else:
                    parts.append(_text(e, name_of, custom_render))
            lines.append(f"[dim]{'  '.join(parts)}[/dim]")
        elif typ == "divider":
            lines.append(f"[dim]{_RULE}[/dim]")
        elif typ == "image":
            label = b.get("title", {}).get("text") or b.get("alt_text", "image")
            lines.append(_img(b.get("image_url", ""), label, image_render))
        elif typ == "actions":
            labels = [_control_label(e) for e in b.get("elements", [])]
            lines.append("  ".join(f"[dim]\\[{escape(x)}][/dim]" for x in labels))
            interactive = True
        else:
            lines.append(f"[dim]\\[unsupported block: {escape(str(typ))}][/dim]")
    return lines, interactive


def _render_attachments(
    attachments: list, name_of: NameOf, custom_render: CustomRender,
    image_render: ImageRender = None,
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
        for key in ("image_url", "thumb_url"):
            if a.get(key):
                lines.append(f"{bar} " + _img(a[key], a.get("title", "image"), image_render))
        if a.get("footer"):
            lines.append(f"[dim]{escape(a['footer'])}[/dim]")
    return lines
