# slak — Terminal Slack client
# Copyright (C) 2026 Toni Leino
# SPDX-License-Identifier: GPL-3.0-or-later

import datetime
import pathlib
import re
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
from bump_version import next_version  # noqa: E402

_CALVER = re.compile(r"^\d{2}\.\d{1,2}\.\d+$")


def test_current_version_is_calendar_versioned():
    import slak.version
    version = tomllib.load(open("pyproject.toml", "rb"))["project"]["version"]
    assert _CALVER.match(version)            # YY.M.N
    assert slak.version.__version__ == version


def test_next_version_uses_year_and_month():
    v = next_version(datetime.date(2026, 6, 22))
    assert v.startswith("26.6.")             # YY.M from the date
    assert _CALVER.match(v)


def test_next_version_handles_double_digit_month():
    assert next_version(datetime.date(2026, 12, 1)).startswith("26.12.")
