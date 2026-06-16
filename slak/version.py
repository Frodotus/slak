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

"""Single source of version and attribution (overview §10).

Keep ``__version__`` in step with ``pyproject.toml``. ``version_line`` is the
one-line footer shown in the help modal and (eventually) ``slak --version``; it
carries the unofficial / TOS warning the overview requires.
"""

from __future__ import annotations

__version__ = "0.1.0"

AUTHOR = "Toni Leino"
URL = "https://github.com/Frodotus/slak"
TOS_WARNING = (
    "Unofficial — uses Slack's internal protocol and may violate Slack's TOS. "
    "Not affiliated with Slack Technologies, LLC."
)


def version_line() -> str:
    """A single attribution/version line for footers and ``--version``."""
    return f"slak {__version__} · {AUTHOR} · {URL}\n{TOS_WARNING}"
