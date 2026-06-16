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

"""Text utilities shared across matching/filtering sites.

`fold` is the single accent-insensitive matching primitive: every fuzzy/filter
site folds both the query and the candidate so that e.g. "melanie" matches
"Mélanie". Display strings are never mutated; folding happens only at match time.
"""

from __future__ import annotations

import unicodedata


def fold(s: str) -> str:
    """Return an accent- and case-insensitive form of ``s``.

    Decompose (NFD), drop combining marks, recompose (NFC), then lowercase.
    Falls back to a plain lowercase if normalization fails for any reason.
    For pure ASCII this is exactly ``s.lower()``.
    """
    try:
        decomposed = unicodedata.normalize("NFD", s)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        return unicodedata.normalize("NFC", stripped).lower()
    except (TypeError, ValueError):
        return s.lower()
