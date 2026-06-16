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

"""Persistent token store.

Browser session credentials live one-file-per-workspace under the XDG data dir,
mode 0600. These files are the credential store; config TOML only references
workspaces by slug/team id.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from slak.slack import Token

_DEFAULT_DIR = Path.home() / ".local" / "share" / "slak" / "tokens"


def _dir(base_dir: Path | None) -> Path:
    return base_dir if base_dir is not None else _DEFAULT_DIR


def save_token(token: Token, base_dir: Path | None = None) -> Path:
    d = _dir(base_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{token.team_id}.json"
    path.write_text(json.dumps(asdict(token), indent=2))
    os.chmod(path, 0o600)
    return path


def load_token(team_id: str, base_dir: Path | None = None) -> Token | None:
    path = _dir(base_dir) / f"{team_id}.json"
    if not path.exists():
        return None
    return Token(**json.loads(path.read_text()))


def load_tokens(base_dir: Path | None = None) -> list[Token]:
    d = _dir(base_dir)
    if not d.exists():
        return []
    return [Token(**json.loads(p.read_text())) for p in sorted(d.glob("*.json"))]
