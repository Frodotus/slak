#!/usr/bin/env python3
# slak — Terminal Slack client
# Copyright (C) 2026 Toni Leino
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bump slak to the next calendar version and write it everywhere.

slak uses calendar versioning ``YY.M.N``:
  * ``YY`` — two-digit year (e.g. 26)
  * ``M``  — month, not zero-padded (1–12)
  * ``N``  — the Nth release in that month (1-based)

e.g. the third release in June 2026 is ``26.6.3``.

``next_version()`` derives N from the existing ``vYY.M.*`` git tags, so running
this picks the right number automatically. It rewrites ``pyproject.toml`` and
``slak/version.py`` and prints the new version (for the release step to tag).
"""

from __future__ import annotations

import datetime
import pathlib
import re
import subprocess


def next_version(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    yy, month = today.year % 100, today.month
    prefix = f"v{yy}.{month}."
    tags = subprocess.run(
        ["git", "tag", "--list", f"{prefix}*"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    nums = [int(t[len(prefix):]) for t in tags if t[len(prefix):].isdigit()]
    n = max(nums) + 1 if nums else 1
    return f"{yy}.{month}.{n}"


def _write(path: str, pattern: str, version: str) -> None:
    p = pathlib.Path(path)
    p.write_text(re.sub(pattern, f'\\g<1>"{version}"', p.read_text(), count=1))


if __name__ == "__main__":
    version = next_version()
    _write("pyproject.toml", r'(?m)^(version = )"[^"]*"', version)
    _write("slak/version.py", r'(__version__ = )"[^"]*"', version)
    print(version)
