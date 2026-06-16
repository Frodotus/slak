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

"""Desktop notifications: pure decision logic + a platform notifier.

``should_notify`` is a pure function (fully testable). The OS integration lives in
``DesktopNotifier`` behind the ``Notifier`` protocol; tests inject a fake.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol


@dataclass
class NotifyContext:
    enabled: bool
    on_mention: bool
    on_dm: bool
    keywords: list[str]
    is_dm: bool
    is_active_channel: bool
    is_self: bool
    text: str
    self_user_id: str


def should_notify(ctx: NotifyContext) -> bool:
    if not ctx.enabled or ctx.is_self or ctx.is_active_channel:
        return False
    if ctx.on_dm and ctx.is_dm:
        return True
    if ctx.on_mention and ctx.self_user_id and f"<@{ctx.self_user_id}>" in ctx.text:
        return True
    lower = ctx.text.lower()
    return any(kw.lower() in lower for kw in ctx.keywords)


_USER = re.compile(r"<@[UW][A-Z0-9]+\|([^>]+)>")
_USER_BARE = re.compile(r"<@([UW][A-Z0-9]+)>")
_CHAN = re.compile(r"<#[CG][A-Z0-9]+\|([^>]+)>")
_LINK = re.compile(r"<(https?://[^>|]+)\|([^>]+)>")
_LINK_BARE = re.compile(r"<(https?://[^>]+)>")
_EMPHASIS = re.compile(r"[*_~`]")


def strip_markup(text: str) -> str:
    """Reduce Slack mrkdwn to plain text suitable for a notification body."""
    text = _USER.sub(r"@\1", text)
    text = _USER_BARE.sub(r"@\1", text)
    text = _CHAN.sub(r"#\1", text)
    text = _LINK.sub(r"\2", text)
    text = _LINK_BARE.sub(r"\1", text)
    return _EMPHASIS.sub("", text)


def notification_text(
    workspace: str, channel_label: str, sender: str, text: str
) -> tuple[str, str]:
    """Return (title, body). ``channel_label`` is ``#chan`` or a DM sender name."""
    title = f"{workspace}: {channel_label}"
    body = strip_markup(text)[:100]
    return title, body


class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


class FakeNotifier:
    """Records notifications for tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> None:
        self.sent.append((title, body))


class DesktopNotifier:
    """Best-effort OS notification via notify-send (Linux) or osascript (macOS)."""

    def notify(self, title: str, body: str) -> None:
        try:
            if sys.platform == "darwin":
                script = f'display notification {body!r} with title {title!r}'
                subprocess.run(["osascript", "-e", script], check=False)
            elif shutil.which("notify-send"):
                subprocess.run(["notify-send", title, body], check=False)
        except Exception:
            pass  # notifications are best-effort; never crash the app
