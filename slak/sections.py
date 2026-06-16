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

"""Pure sidebar grouping: config-glob (source 3) and Slack-native (source 1)
sections (spec 03 §9)."""

from __future__ import annotations

_HIDDEN_SECTION_TYPES = {"slack_connect", "salesforce", "agents"}


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


def order_native_sections(sections):
    """Order + filter Slack-native sections (objects with ``id``/``type``/``next_id``).

    Follows the ``next_id`` linked list from each head (input order), tolerating
    cycles and multiple heads. Hidden types are dropped; ``recent_apps`` is kept
    only when it has channels; ``stars`` is pinned to the top.
    """
    by_id = {s.id: s for s in sections}
    pointed = {s.next_id for s in sections if s.next_id}
    seen: set[str] = set()
    ordered = []

    def walk(start):
        node = start
        while node is not None and node.id not in seen:
            seen.add(node.id)
            ordered.append(node)
            node = by_id.get(node.next_id)

    for s in sections:  # heads first (not pointed to by anyone), in input order
        if s.id not in pointed:
            walk(s)
    for s in sections:  # then anything left (cycle remnants / orphans)
        if s.id not in seen:
            walk(s)

    def keep(s):
        if s.type in _HIDDEN_SECTION_TYPES:
            return False
        if s.type == "recent_apps":
            return bool(s.channel_ids)
        return True

    kept = [s for s in ordered if keep(s)]
    stars = [s for s in kept if s.type == "stars"]
    rest = [s for s in kept if s.type != "stars"]
    return stars + rest
