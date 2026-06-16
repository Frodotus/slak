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

"""Command palette provider — the discoverable action surface (Ctrl+P).

Exposes context actions (operate on the current selection) and workspace
switches by name. As more features land (react, mark unread, copy permalink,
open thread…) they register here so there's one place to discover them.
"""

from __future__ import annotations

from functools import partial

from textual.command import Hit, Hits, Provider


class PyslkCommands(Provider):
    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        app = self.app

        commands: list[tuple[str, str, str]] = [
            ("Jump to channel", "find_channel", "Fuzzy-find a channel or DM"),
            ("Help: keyboard shortcuts", "help", "Show the keybinding reference"),
            ("Presence: Active", "presence_active", "Set yourself active"),
            ("Presence: Away", "presence_away", "Set yourself away"),
            ("Do Not Disturb: 30 minutes", "snooze(30)", "Snooze notifications 30m"),
            ("Do Not Disturb: 1 hour", "snooze(60)", "Snooze notifications 1h"),
            ("Do Not Disturb: 2 hours", "snooze(120)", "Snooze notifications 2h"),
            ("End Do Not Disturb", "end_dnd", "Turn off snooze"),
            ("Search this channel", "search", "Find messages in the current channel"),
            ("Search all channels", "search_workspace", "Search the whole workspace"),
            ("Add reaction", "react", "React to the selected message"),
            ("Mark unread from here", "mark_unread", "Mark the selected message and newer unread"),
            ("Open thread", "open_thread", "Open the thread for the selected message"),
            ("Close thread", "close_thread", "Hide the thread panel"),
            ("Copy selected message", "copy_message", "Copy the selected message text"),
            ("Go to latest message", "scroll_latest", "Select the newest message"),
            ("Go to oldest message", "scroll_oldest", "Select the oldest loaded message"),
        ]
        for i, team_id in enumerate(app.router.ordered()):
            client = app.router.client(team_id)
            name = client.team_name if client else team_id
            commands.append((f"Switch to {name}", f"switch_workspace({i})", "Switch workspace"))

        for title, action, help_text in commands:
            score = matcher.match(title)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(title),
                    partial(app.run_action, action),
                    help=help_text,
                )
