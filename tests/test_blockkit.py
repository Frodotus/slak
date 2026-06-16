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

from slak.blockkit import render_extras


def joined(raw: dict) -> str:
    return "\n".join(render_extras(json.dumps(raw), name_of=str))


def test_no_blocks_or_attachments_is_empty():
    assert render_extras("", name_of=str) == []
    assert render_extras("not json", name_of=str) == []
    assert render_extras(json.dumps({"text": "hi"}), name_of=str) == []


def test_header_and_section_render():
    out = joined({
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Deploy failed"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "service *api* is down"}},
        ]
    })
    assert "Deploy failed" in out
    assert "service" in out and "api" in out


def test_section_fields_render():
    out = joined({
        "blocks": [
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": "*Env*\nprod"},
                {"type": "mrkdwn", "text": "*Status*\n500"},
            ]}
        ]
    })
    assert "Env" in out and "prod" in out and "Status" in out and "500" in out


def test_divider_and_context():
    out = joined({
        "blocks": [
            {"type": "divider"},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "via CI bot"}]},
        ]
    })
    assert "─" in out
    assert "via CI bot" in out


def test_actions_block_marks_interactive():
    out = joined({
        "blocks": [
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Approve"}},
            ]}
        ]
    })
    assert "Approve" in out
    assert "open in Slack" in out  # interactive footer line


def test_unknown_block_type():
    out = joined({"blocks": [{"type": "wizardry"}]})
    assert "[unsupported block: wizardry]" in out


def test_message_pane_body_includes_blocks():
    from slak.slack import RemoteMessage
    from slak.ui.widgets import MessagePane

    pane = MessagePane()
    raw = json.dumps(
        {"blocks": [{"type": "header", "text": {"type": "plain_text", "text": "Deploy"}}]}
    )
    msg = RemoteMessage("1.0", "u", "hi there", raw_json=raw)
    body = pane._body(msg)
    assert "hi there" in body  # original text kept
    assert "Deploy" in body  # block rendered too


def test_legacy_attachment_renders_fields_and_color():
    lines = render_extras(json.dumps({
        "attachments": [
            {"color": "danger", "pretext": "Heads up", "title": "Build #42",
             "text": "failed on main", "footer": "CI"},
        ]
    }), name_of=str)
    out = "\n".join(lines)
    assert "Heads up" in out
    assert "Build #42" in out
    assert "failed on main" in out
    assert "CI" in out
    assert "red" in out  # danger → red colour bar markup
