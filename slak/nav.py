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

"""Per-workspace channel navigation history (``Alt+←``/``Alt+→``, spec 03 §7).

A browser-style back/forward stack over channel ids. A fresh :meth:`visit`
truncates the forward path; :meth:`back`/:meth:`forward` accept an optional set
of still-valid channel ids and silently skip (discard) any stale entries.
"""

from __future__ import annotations


class NavHistory:
    def __init__(self) -> None:
        self._back: list[str] = []
        self._cur: str | None = None
        self._fwd: list[str] = []

    def current(self) -> str | None:
        return self._cur

    def visit(self, channel_id: str) -> None:
        """Record a brand-new navigation (not a back/forward move)."""
        if channel_id == self._cur:
            return
        if self._cur is not None:
            self._back.append(self._cur)
        self._cur = channel_id
        self._fwd.clear()

    def back(self, valid: set[str] | None = None) -> str | None:
        """Move to the previous channel, skipping any no longer in ``valid``."""
        while self._back:
            cand = self._back.pop()
            if valid is None or cand in valid:
                if self._cur is not None:
                    self._fwd.append(self._cur)
                self._cur = cand
                return cand
        return None

    def forward(self, valid: set[str] | None = None) -> str | None:
        """Move to the next channel, skipping any no longer in ``valid``."""
        while self._fwd:
            cand = self._fwd.pop()
            if valid is None or cand in valid:
                if self._cur is not None:
                    self._back.append(self._cur)
                self._cur = cand
                return cand
        return None
