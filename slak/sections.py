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

"""Pure sidebar grouping for config-glob sections (spec 03 §9, source 3)."""

from __future__ import annotations


def layout(section_names, match, channels):
    """Group ``channels`` into ``(section_name | None, channels)`` buckets.

    Named sections appear in ``section_names`` order (empty ones dropped); any
    channel that matches no section falls into a trailing ``None`` bucket.
    ``match(channel_name) -> section_name | None`` decides membership.
    """
    buckets: dict[str, list] = {name: [] for name in section_names}
    ungrouped: list = []
    for ch in channels:
        name = match(ch.name)
        if name in buckets:
            buckets[name].append(ch)
        else:
            ungrouped.append(ch)
    result = [(name, buckets[name]) for name in section_names if buckets[name]]
    if ungrouped:
        result.append((None, ungrouped))
    return result
