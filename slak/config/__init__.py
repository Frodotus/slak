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

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field

import tomlkit

from slak.text import fold

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


def _parse_sections(raw: dict) -> dict[str, list[str]]:
    """Normalise a ``[sections.*]`` block to ``{name: [glob, …]}``.

    Accepts both the TOML form (``[sections.Eng] patterns = [...]``) and a plain
    ``name -> [glob]`` mapping.
    """
    out: dict[str, list[str]] = {}
    for name, val in raw.items():
        out[name] = list(val.get("patterns", [])) if isinstance(val, dict) else list(val)
    return out


@dataclass
class WorkspaceConfig:
    slug: str
    team_id: str | None = None
    theme: str | None = None
    order: int = 0
    use_slack_sections: bool | None = None
    sections: dict[str, list[str]] | None = None


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
    mcp_enabled: bool = False
    mcp_socket_path: str | None = None
    sections: dict[str, list[str]] = field(default_factory=dict)
    workspaces: list[WorkspaceConfig] = field(default_factory=list)

    @classmethod
    def loads(cls, text: str) -> "Config":
        data = tomllib.loads(text) if text.strip() else {}
        general = data.get("general", {})
        appearance = data.get("appearance", {})
        notif = data.get("notifications", {})
        mcp = data.get("mcp", {})

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
                    sections=(
                        _parse_sections(block["sections"])
                        if "sections" in block
                        else None
                    ),
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
            mcp_enabled=bool(mcp.get("enabled", False)),
            mcp_socket_path=mcp.get("socket_path"),
            sections=_parse_sections(data.get("sections", {})),
            workspaces=workspaces,
        )

    def dumps(self) -> str:
        """Serialise to TOML (round-trips through :meth:`loads`).

        Comment/formatting preservation of a hand-edited file is a future
        refinement; this writes a clean, canonical document.
        """
        doc = tomlkit.document()

        general = tomlkit.table()
        if self.default_workspace is not None:
            general["default_workspace"] = self.default_workspace
        general["use_slack_sections"] = self.use_slack_sections
        doc["general"] = general

        appearance = tomlkit.table()
        appearance["theme"] = self.theme
        appearance["group_within_minutes"] = self.group_within_minutes
        appearance["image_protocol"] = self.image_protocol
        appearance["emoji_images"] = self.emoji_images
        doc["appearance"] = appearance

        notif = tomlkit.table()
        notif["enabled"] = self.notify_enabled
        notif["on_mention"] = self.notify_on_mention
        notif["on_dm"] = self.notify_on_dm
        notif["on_keyword"] = self.notify_keywords
        doc["notifications"] = notif

        if self.mcp_enabled or self.mcp_socket_path:
            mcp = tomlkit.table()
            mcp["enabled"] = self.mcp_enabled
            if self.mcp_socket_path:
                mcp["socket_path"] = self.mcp_socket_path
            doc["mcp"] = mcp

        if self.theme_overrides:
            doc["theme"] = self.theme_overrides

        if self.sections:
            sec_table = tomlkit.table()
            for name, globs in self.sections.items():
                block = tomlkit.table()
                block["patterns"] = globs
                sec_table[name] = block
            doc["sections"] = sec_table

        if self.workspaces:
            ws_table = tomlkit.table()
            for ws in self.workspaces:
                block = tomlkit.table()
                if ws.team_id is not None:
                    block["team_id"] = ws.team_id
                if ws.theme is not None:
                    block["theme"] = ws.theme
                if ws.order:
                    block["order"] = ws.order
                if ws.use_slack_sections is not None:
                    block["use_slack_sections"] = ws.use_slack_sections
                if ws.sections is not None:
                    ws_sec = tomlkit.table()
                    for name, globs in ws.sections.items():
                        inner = tomlkit.table()
                        inner["patterns"] = globs
                        ws_sec[name] = inner
                    block["sections"] = ws_sec
                ws_table[ws.slug] = block
            doc["workspaces"] = ws_table

        return tomlkit.dumps(doc)

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

    def set_workspace_theme(self, team_id: str, theme: str, slug: str | None = None) -> None:
        """Set the per-workspace theme, creating a workspace entry if needed."""
        ws = self._by_team_id(team_id)
        if ws is None:
            ws = WorkspaceConfig(slug=slug or team_id, team_id=team_id)
            self.workspaces.append(ws)
        ws.theme = theme

    def set_default_theme(self, theme: str) -> None:
        """Set the global default theme for workspaces without their own."""
        self.theme = theme

    def uses_slack_sections(self, team_id: str) -> bool:
        """Whether to use Slack-native sections for a workspace (per-ws → global)."""
        ws = self._by_team_id(team_id)
        if ws is not None and ws.use_slack_sections is not None:
            return ws.use_slack_sections
        return self.use_slack_sections

    def sections_for(self, team_id: str) -> dict[str, list[str]]:
        """Section globs for a workspace — per-workspace fully replaces global."""
        ws = self._by_team_id(team_id)
        if ws is not None and ws.sections is not None:
            return ws.sections
        return self.sections

    def match_section(self, team_id: str, channel_name: str) -> str | None:
        """The first config section whose globs match ``channel_name`` (or None)."""
        folded = fold(channel_name)
        for name, globs in self.sections_for(team_id).items():
            if any(fnmatch.fnmatchcase(folded, fold(g)) for g in globs):
                return name
        return None

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
