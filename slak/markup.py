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

"""Escaping for Textual content markup.

Textual (8.x) renders widget content with its own *content markup*, not Rich
markup. The two dialects differ in what counts as a tag: ``rich.markup.escape``
leaves ``[0]`` and ``[$1::DATE]`` untouched (they aren't valid Rich tags), but
Textual treats any ``[…]`` as a tag — and ``[$name]`` as a variable — so those
crash with ``MarkupError``. We therefore backslash-escape *every* ``[`` (the only
tag-opening character); Textual renders ``\\[`` as a literal bracket. ``]`` needs
no escaping. Use this in place of ``rich.markup.escape`` for any untrusted text
spliced into a markup string.
"""

from __future__ import annotations


def escape(text: str) -> str:
    """Neutralise Textual content markup in ``text`` by escaping every ``[``."""
    return text.replace("[", "\\[")
