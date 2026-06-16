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

"""Configuration model: load, resolve themes, order workspaces.

Config is read from ``~/.config/slak/config.toml``. Workspaces are keyed by a
readable *slug* with an explicit ``team_id``; legacy blocks keyed directly by a
Slack team id (matching ``^[TE][A-Z0-9]{6,}$``) remain supported.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field

LEGACY_TEAM_ID = re.compile(r"^[TE][A-Z0-9]{6,}$")
DEFAULT_THEME = "dark"


def slugify(name: str, existing: set[str]) -> str:
    """Derive a readable workspace slug from a team name.

    Lowercase, collapse runs of non-alphanumerics to ``-``, trim edges, then
    de-duplicate against ``existing`` with ``-2``/``-3``/… suffixes.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


@dataclass
class WorkspaceConfig:
    slug: str
    team_id: str | None = None
    theme: str | None = None
    order: int = 0
    use_slack_sections: bool | None = None


@dataclass
class Config:
    default_workspace: str | None = None
    theme: str = DEFAULT_THEME
    theme_overrides: dict[str, str] = field(default_factory=dict)
    use_slack_sections: bool = True
    group_within_minutes: int = 0
    image_protocol: str = "auto"  # auto | kitty | sixel | halfblock | off
    emoji_images: str = "on"  # on | off — kitty inline custom-emoji images
    notify_enabled: bool = True
    notify_on_mention: bool = True
    notify_on_dm: bool = True
    notify_keywords: list[str] = field(default_factory=list)
    workspaces: list[WorkspaceConfig] = field(default_factory=list)

    @classmethod
    def loads(cls, text: str) -> "Config":
        data = tomllib.loads(text) if text.strip() else {}
        general = data.get("general", {})
        appearance = data.get("appearance", {})
        notif = data.get("notifications", {})

        workspaces: list[WorkspaceConfig] = []
        for slug, block in data.get("workspaces", {}).items():
            team_id = block.get("team_id")
            if team_id is None and LEGACY_TEAM_ID.match(slug):
                team_id = slug
            workspaces.append(
                WorkspaceConfig(
                    slug=slug,
                    team_id=team_id,
                    theme=block.get("theme"),
                    order=int(block.get("order", 0)),
                    use_slack_sections=block.get("use_slack_sections"),
                )
            )

        return cls(
            default_workspace=general.get("default_workspace"),
            theme=appearance.get("theme", DEFAULT_THEME),
            theme_overrides=dict(data.get("theme", {})),
            use_slack_sections=bool(general.get("use_slack_sections", True)),
            group_within_minutes=int(appearance.get("group_within_minutes", 0)),
            image_protocol=appearance.get("image_protocol", "auto"),
            emoji_images=appearance.get("emoji_images", "on"),
            notify_enabled=bool(notif.get("enabled", True)),
            notify_on_mention=bool(notif.get("on_mention", True)),
            notify_on_dm=bool(notif.get("on_dm", True)),
            notify_keywords=list(notif.get("on_keyword", [])),
            workspaces=workspaces,
        )

    def _by_team_id(self, team_id: str) -> WorkspaceConfig | None:
        for ws in self.workspaces:
            if ws.team_id == team_id:
                return ws
        return None

    def resolve_theme(self, team_id: str) -> str:
        ws = self._by_team_id(team_id)
        if ws is not None and ws.theme:
            return ws.theme
        return self.theme or DEFAULT_THEME

    def slug_for(self, team_id: str) -> str | None:
        ws = self._by_team_id(team_id)
        return ws.slug if ws is not None else None

    def order_team_ids(self, all_team_ids: list[str]) -> list[str]:
        """Return ``all_team_ids`` in stable rail order.

        Bucket A: configured with order > 0, ascending (ties by slug).
        Bucket B: configured without an order, by slug.
        Bucket C: unconfigured, by team id.
        """
        known = set(all_team_ids)
        configured = {
            ws.team_id: ws for ws in self.workspaces if ws.team_id in known
        }

        bucket_a = sorted(
            (ws for ws in configured.values() if ws.order > 0),
            key=lambda ws: (ws.order, ws.slug),
        )
        bucket_b = sorted(
            (ws for ws in configured.values() if ws.order <= 0),
            key=lambda ws: ws.slug,
        )
        bucket_c = sorted(tid for tid in known if tid not in configured)

        return [ws.team_id for ws in bucket_a] + [ws.team_id for ws in bucket_b] + bucket_c
