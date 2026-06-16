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

from slak.blockkit import image_urls, render_extras


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


def test_rich_text_block_is_not_shown_as_unsupported():
    # rich_text is how normal messages carry their body; the `text` field already
    # holds it, so the block renders nothing (no noise, no duplication).
    lines = render_extras(
        json.dumps({"blocks": [{"type": "rich_text", "elements": []}]}),
        name_of=str,
    )
    assert lines == []


def test_message_with_text_and_rich_text_renders_text_once():
    from slak.slack import RemoteMessage
    from slak.ui.widgets import MessagePane

    raw = json.dumps({"blocks": [{"type": "rich_text", "elements": []}]})
    body = MessagePane()._body(RemoteMessage("1.0", "u", "hello world", raw_json=raw))
    assert "hello world" in body
    assert "unsupported" not in body


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


def test_image_urls_collects_from_blocks_and_attachments():
    raw = json.dumps({
        "blocks": [
            {"type": "image", "image_url": "http://x/a.png", "alt_text": "a"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "hi"},
             "accessory": {"type": "image", "image_url": "http://x/b.png"}},
            {"type": "context", "elements": [
                {"type": "image", "image_url": "http://x/c.png"},
                {"type": "mrkdwn", "text": "ignored"},
            ]},
        ],
        "attachments": [
            {"image_url": "http://x/d.png", "thumb_url": "http://x/e.png"},
        ],
    })
    assert image_urls(raw) == [
        "http://x/a.png", "http://x/b.png", "http://x/c.png",
        "http://x/d.png", "http://x/e.png",
    ]


def test_image_urls_includes_image_files():
    raw = json.dumps({
        "files": [
            {"mimetype": "image/png", "thumb_360": "https://files.slack.com/a-360.png",
             "url_private": "https://files.slack.com/a.png"},
            {"mimetype": "application/pdf", "url_private": "https://files.slack.com/d.pdf"},
        ]
    })
    assert image_urls(raw) == ["https://files.slack.com/a-360.png"]


def test_image_file_renders_via_callback():
    raw = json.dumps({"files": [
        {"mimetype": "image/png", "thumb_360": "u360", "name": "pic.png"},
    ]})
    lines = render_extras(raw, name_of=str, image_render=lambda u: "[IMG]" if u == "u360" else None)
    assert any("[IMG]" in ln for ln in lines)
    # fallback to a labelled placeholder when not ready
    lines = render_extras(raw, name_of=str, image_render=lambda u: None)
    assert any("pic.png" in ln for ln in lines)


def test_image_urls_empty_and_invalid():
    assert image_urls("") == []
    assert image_urls("nope") == []
    assert image_urls(json.dumps({"text": "hi"})) == []


def test_image_block_uses_render_callback_when_available():
    raw = json.dumps({"blocks": [
        {"type": "image", "image_url": "http://x/a.png", "alt_text": "chart"},
    ]})
    # callback returns a placeholder for the ready image
    lines = render_extras(raw, name_of=str, image_render=lambda u: "[IMG:a]")
    assert any("[IMG:a]" in ln for ln in lines)
    # without a ready image, falls back to the labelled placeholder
    lines = render_extras(raw, name_of=str, image_render=lambda u: None)
    assert any("chart" in ln for ln in lines)


def test_attachment_image_is_on_its_own_line_without_bar_prefix():
    # a multi-row image placeholder must start at column 0 (every row aligned),
    # not be prefixed by the attachment's "▎" bar on the first row only.
    placeholder = "ROW0\nROW1\nROW2"
    raw = json.dumps({"attachments": [
        {"color": "danger", "title": "t", "image_url": "u"},
    ]})
    lines = render_extras(raw, name_of=str, image_render=lambda url: placeholder)
    assert placeholder in lines  # exact, unprefixed entry


def test_context_image_is_on_its_own_line():
    placeholder = "IMG0\nIMG1"
    raw = json.dumps({"blocks": [{"type": "context", "elements": [
        {"type": "mrkdwn", "text": "via bot"},
        {"type": "image", "image_url": "u", "alt_text": "icon"},
    ]}]})
    lines = render_extras(raw, name_of=str, image_render=lambda url: placeholder)
    assert placeholder in lines  # not inlined with the "via bot" text


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


def test_thread_indicator_shown_for_messages_with_replies():
    from slak.slack import RemoteMessage
    from slak.ui.widgets import MessagePane

    pane = MessagePane()
    assert "3 replies" in pane._body(RemoteMessage("1.0", "u", "parent", reply_count=3))
    assert "1 reply" in pane._body(RemoteMessage("2.0", "u", "p", reply_count=1))
    assert "repl" not in pane._body(RemoteMessage("3.0", "u", "no thread"))
