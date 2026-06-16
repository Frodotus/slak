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

"""Tiny opt-in file logger for diagnosing issues without a TUI console.

Set ``SLAK_DEBUG=1`` to write to ``slak-debug.log`` in the working directory
(truncated on first write each run). No-op otherwise.
"""

from __future__ import annotations

import os
import time

_PATH = "slak-debug.log"
_ENABLED = os.environ.get("SLAK_DEBUG") == "1"
_started = False


def debug(msg: str) -> None:
    global _started
    if not _ENABLED:
        return
    try:
        with open(_PATH, "w" if not _started else "a") as fh:
            fh.write(f"{time.monotonic():9.3f}  {msg}\n")
        _started = True
    except Exception:
        pass
