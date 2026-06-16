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

import json

from slak.config import Config
from slak.mcp import build_snapshot, handle_request, message_dict
from slak.slack import Reaction, RemoteMessage


def test_message_dict_resolves_name_and_reactions():
    rm = RemoteMessage("100.0", "U2", "hello", reactions=[Reaction("+1", 3, ["U2"])])
    d = message_dict(rm, name_of=lambda u: {"U2": "bob"}.get(u, u))
    assert d == {
        "ts": "100.0",
        "user": "bob",
        "text": "hello",
        "reactions": [{"emoji": "+1", "count": 3}],
    }


def test_build_snapshot_shape():
    snap = build_snapshot(
        workspace="Acme",
        channel={"id": "C1", "name": "general", "type": "channel"},
        selected={"ts": "100.0", "user": "bob", "text": "hi", "reactions": []},
        thread={"open": False},
        recent=[{"ts": "100.0", "user": "bob", "text": "hi", "reactions": []}],
    )
    assert snap["workspace"] == "Acme"
    assert snap["channel"]["name"] == "general"
    assert snap["thread"] == {"open": False}
    assert len(snap["recent_messages"]) == 1


def test_handle_request_get_context():
    snap = {"workspace": "Acme"}
    resp = handle_request(
        json.dumps({"id": 1, "method": "get_context"}),
        get_snapshot=lambda: snap,
        set_draft=lambda t: {},
    )
    assert resp == {"id": 1, "result": snap}


def test_handle_request_set_draft_calls_setter():
    seen = {}

    def setter(text):
        seen["text"] = text
        return {"target": "channel", "channel": "C1", "ok": True}

    resp = handle_request(
        json.dumps({"id": 2, "method": "set_draft", "params": {"text": "hi there"}}),
        get_snapshot=lambda: {},
        set_draft=setter,
    )
    assert seen["text"] == "hi there"
    assert resp["result"]["ok"] is True


def test_handle_request_unknown_method_and_bad_json():
    bad = handle_request("{not json", get_snapshot=dict, set_draft=lambda t: {})
    assert "error" in bad
    unknown = handle_request(
        json.dumps({"id": 3, "method": "frobnicate"}),
        get_snapshot=dict,
        set_draft=lambda t: {},
    )
    assert "error" in unknown


def test_config_mcp_disabled_by_default_and_parsed():
    assert Config().mcp_enabled is False
    cfg = Config.loads("[mcp]\nenabled = true\nsocket_path = \"/tmp/x.sock\"\n")
    assert cfg.mcp_enabled is True
    assert cfg.mcp_socket_path == "/tmp/x.sock"
    # round-trips
    assert Config.loads(cfg.dumps()).mcp_enabled is True
