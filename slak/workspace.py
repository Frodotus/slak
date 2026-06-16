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

"""Multi-workspace router.

Holds every connected workspace client and a single active pointer. Callbacks
read ``active()`` at invocation time (rather than capturing a client), so
switching workspaces is just moving the pointer — no closures to rebind.
"""

from __future__ import annotations

from slak.slack import SlackClient


class WorkspaceRouter:
    def __init__(self, clients: list[SlackClient], order: list[str]):
        self._clients: dict[str, SlackClient] = {c.team_id: c for c in clients}
        self._order: list[str] = [t for t in order if t in self._clients]
        # any known clients missing from `order` are appended deterministically
        for tid in sorted(self._clients):
            if tid not in self._order:
                self._order.append(tid)
        self._active: str | None = self._order[0] if self._order else None

    @classmethod
    def single(cls, client: SlackClient) -> "WorkspaceRouter":
        return cls([client], order=[client.team_id])

    def ordered(self) -> list[str]:
        return list(self._order)

    def clients_in_order(self) -> list[SlackClient]:
        return [self._clients[t] for t in self._order]

    def all(self) -> list[SlackClient]:
        return list(self._clients.values())

    def client(self, team_id: str) -> SlackClient | None:
        return self._clients.get(team_id)

    def active(self) -> SlackClient | None:
        return self._clients.get(self._active) if self._active else None

    def active_team_id(self) -> str | None:
        return self._active

    def set_active(self, team_id: str) -> bool:
        if team_id not in self._clients:
            return False
        self._active = team_id
        return True

    def set_active_index(self, index: int) -> bool:
        if 0 <= index < len(self._order):
            self._active = self._order[index]
            return True
        return False
