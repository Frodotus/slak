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

from slak.notify import NotifyContext, notification_text, should_notify, strip_markup


def ctx(**kw) -> NotifyContext:
    base = dict(
        enabled=True, on_mention=True, on_dm=True, keywords=[],
        is_dm=False, is_active_channel=False, is_self=False,
        text="hello", self_user_id="U1",
    )
    base.update(kw)
    return NotifyContext(**base)


def test_notifies_on_dm():
    assert should_notify(ctx(is_dm=True)) is True


def test_notifies_on_mention():
    assert should_notify(ctx(text="hey <@U1> look")) is True


def test_notifies_on_keyword_case_insensitive():
    assert should_notify(ctx(keywords=["deploy"], text="DEPLOY now")) is True


def test_no_notification_for_plain_channel_message():
    assert should_notify(ctx(text="just chatting")) is False


def test_never_notifies_for_own_message():
    assert should_notify(ctx(is_dm=True, is_self=True)) is False


def test_never_notifies_for_active_channel():
    assert should_notify(ctx(is_dm=True, is_active_channel=True)) is False


def test_disabled_suppresses_everything():
    assert should_notify(ctx(enabled=False, is_dm=True)) is False


def test_on_dm_toggle_off():
    assert should_notify(ctx(is_dm=True, on_dm=False)) is False


def test_strip_markup_renders_entities_and_emphasis():
    raw = "hey <@U1|alice> see <#C2|general> at <https://x.io|the link> *now* `code`"
    assert strip_markup(raw) == "hey @alice see #general at the link now code"


def test_notification_text_title_and_body():
    title, body = notification_text("Acme", "#general", "Alice", "deploy <@U1> done")
    assert title == "Acme: #general"
    assert body == "deploy @U1 done"
