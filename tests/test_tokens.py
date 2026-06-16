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

import stat

from slak.slack import Token
from slak.slack.tokens import load_token, load_tokens, save_token


def test_save_then_load_round_trips(tmp_path):
    tok = Token(
        access_token="xoxc-abc",
        cookie="d-cookie-value",
        team_id="T1",
        team_name="Acme",
        team_domain="acme",
    )
    save_token(tok, base_dir=tmp_path)
    loaded = load_token("T1", base_dir=tmp_path)
    assert loaded == tok


def test_token_file_is_private(tmp_path):
    save_token(Token("xoxc-x", "d", "T1"), base_dir=tmp_path)
    path = tmp_path / "T1.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_load_tokens_lists_all(tmp_path):
    save_token(Token("a", "d", "T1", "One"), base_dir=tmp_path)
    save_token(Token("b", "d", "T2", "Two"), base_dir=tmp_path)
    teams = sorted(t.team_id for t in load_tokens(base_dir=tmp_path))
    assert teams == ["T1", "T2"]


def test_load_token_missing_returns_none(tmp_path):
    assert load_token("TNOPE", base_dir=tmp_path) is None


def test_load_tokens_empty_when_no_dir(tmp_path):
    assert load_tokens(base_dir=tmp_path / "absent") == []
