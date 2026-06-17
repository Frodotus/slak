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

"""Render inbound Slack message text into safe Rich markup for display.

Slack sends a wire format: ``<@U123>`` mentions, ``<#C1|name>`` channel refs,
``<!here>`` broadcasts, ``<url|label>`` links, and HTML-escaped ``&amp;``. This
turns those into readable text, expands ``:emoji:`` shortcodes, escapes any
literal Rich markup (so message text can't break the layout), and converts
mrkdwn emphasis (``*bold*``, ``_italic_``) into Rich tags.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

from slak.markup import escape

from slak.emoji import emojize

_USER = re.compile(r"<@(\w+)(?:\|([^>]+))?>")
_CHAN = re.compile(r"<#(\w+)(?:\|([^>]+))?>")
_SUBTEAM = re.compile(r"<!subteam\^(\w+)(?:\|([^>]+))?>")
_BROADCAST = re.compile(r"<!(\w+)(?:\|([^>]+))?>")
_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]+))?>")

_BOLD = re.compile(r"\*([^*\n]+)\*")
_ITALIC = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_STRIKE = re.compile(r"~([^~\n]+)~")
_CODE = re.compile(r"`([^`\n]+)`")
_CUSTOM = re.compile(r":([a-zA-Z0-9_+\-]+):")


def render_message(
    text: str,
    name_of: Callable[[str], str],
    custom_render: Callable[[str], str | None] | None = None,
) -> str:
    def user(m: re.Match) -> str:
        name = name_of(m.group(1))
        if name == m.group(1) and m.group(2):
            name = m.group(2)
        return "@" + name

    # 1. entities (operate on the real angle-bracket tokens first)
    text = _USER.sub(user, text)
    text = _CHAN.sub(lambda m: "#" + (m.group(2) or m.group(1)), text)
    text = _SUBTEAM.sub(lambda m: m.group(2) or "@team", text)
    text = _BROADCAST.sub(lambda m: "@" + (m.group(2) or m.group(1)), text)
    text = _LINK.sub(lambda m: m.group(2) or m.group(1).replace("mailto:", ""), text)
    # 2. unescape Slack's HTML entities, now that tokens are gone
    text = html.unescape(text)
    # 3. emoji shortcodes -> glyphs (custom/unknown left as :name:)
    text = emojize(text)
    # 4. neutralise any literal Rich markup in the message body
    text = escape(text)
    # 5. mrkdwn emphasis -> Rich tags (added after escaping, so they're real)
    text = _BOLD.sub(r"[b]\1[/b]", text)
    text = _ITALIC.sub(r"[i]\1[/i]", text)
    text = _STRIKE.sub(r"[s]\1[/s]", text)
    text = _CODE.sub(r"[reverse]\1[/reverse]", text)
    # 6. custom emoji: let the caller decide how to render them (kitty image
    #    placeholder when ready, a chip fallback otherwise, or None to leave text)
    if custom_render:
        text = _CUSTOM.sub(
            lambda m: custom_render(m.group(1)) or m.group(0), text
        )
    return text
