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

"""Extract openable URLs from a Slack message (``Ctrl+O``, spec 04).

Handles Slack's angle-wrapped link entities (``<url>`` and ``<url|label>``) and
bare URLs, returned in document order with duplicates collapsed.
"""

from __future__ import annotations

import re

_ANGLE = re.compile(r"<(https?://[^|>]+)(?:\|[^>]+)?>")
_BARE = re.compile(r"https?://[^\s<>|]+")
_TRAILING = ".,;:)]}>\"'"


def extract_links(text: str) -> list[str]:
    """Return the http(s) URLs in ``text``, in order, without duplicates."""
    found: list[tuple[int, str]] = [
        (m.start(), m.group(1)) for m in _ANGLE.finditer(text)
    ]
    # Mask angle spans so bare-URL scanning doesn't re-match their contents.
    masked = _ANGLE.sub(lambda m: " " * (m.end() - m.start()), text)
    found += [
        (m.start(), m.group(0).rstrip(_TRAILING)) for m in _BARE.finditer(masked)
    ]
    found.sort(key=lambda t: t[0])

    seen: set[str] = set()
    urls: list[str] = []
    for _, url in found:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
