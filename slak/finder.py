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

"""Pure ranking for the channel/DM finder (``Ctrl+K``, spec 03 §5).

``rank_channels`` is accent-insensitive (via :func:`slak.text.fold`) and stable:
an empty query returns the input untouched (recency order, set by the caller),
and a non-empty query keeps only matches, ordered by match tier with the
original recency order preserved within each tier.
"""

from __future__ import annotations

from slak.text import fold

# Match tiers, best (lowest) first.
_EXACT, _PREFIX, _SUBSTRING, _SUBSEQUENCE, _NONE = range(5)


def _is_subsequence(query: str, candidate: str) -> bool:
    """True if every char of ``query`` appears in ``candidate`` in order."""
    it = iter(candidate)
    return all(c in it for c in query)


def _tier(query: str, candidate: str) -> int:
    """Best match tier of a folded ``query`` against a folded ``candidate``."""
    if query == candidate:
        return _EXACT
    if candidate.startswith(query):
        return _PREFIX
    if query in candidate:
        return _SUBSTRING
    if _is_subsequence(query, candidate):
        return _SUBSEQUENCE
    return _NONE


def rank_channels(channels, query: str):
    """Filter and order ``channels`` (objects with ``.name``) for the finder.

    Empty/whitespace query → ``channels`` unchanged. Otherwise → only matching
    channels, ordered by match tier; ties keep the incoming (recency) order.
    """
    q = fold(query.strip())
    if not q:
        return list(channels)
    scored = []
    for i, ch in enumerate(channels):
        tier = _tier(q, fold(ch.name))
        if tier != _NONE:
            scored.append((tier, i, ch))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [ch for _, _, ch in scored]
