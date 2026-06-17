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

from slak.config import Config, WorkspaceConfig


def roundtrip(cfg: Config) -> Config:
    return Config.loads(cfg.dumps())


def test_dumps_then_loads_preserves_core_fields():
    cfg = Config(
        default_workspace="acme",
        theme="dracula",
        image_protocol="kitty",
        emoji_images="off",
        notify_keywords=["ping", "release"],
    )
    out = roundtrip(cfg)
    assert out.default_workspace == "acme"
    assert out.theme == "dracula"
    assert out.image_protocol == "kitty"
    assert out.emoji_images == "off"
    assert out.notify_keywords == ["ping", "release"]


def test_image_preview_defaults_to_terminal_and_roundtrips():
    assert Config().image_preview == "terminal"
    assert roundtrip(Config(image_preview="gui")).image_preview == "gui"


def test_colored_names_defaults_off_and_roundtrips():
    assert Config().colored_names is False
    assert roundtrip(Config(colored_names=True)).colored_names is True


def test_recent_reactions_roundtrip_and_record_is_mru():
    cfg = Config()
    assert cfg.recent_reactions == []
    cfg.record_reaction("tada")
    cfg.record_reaction("+1")
    cfg.record_reaction("tada")            # re-use moves to front, no dup
    assert cfg.recent_reactions == ["tada", "+1"]
    assert roundtrip(cfg).recent_reactions == ["tada", "+1"]
    for i in range(30):
        cfg.record_reaction(f"e{i}")
    assert len(cfg.recent_reactions) <= 16  # capped


def test_nicknames_roundtrip_and_set_helper():
    cfg = Config()
    assert cfg.nicknames == {}
    cfg.set_nickname("U1", "Boss")
    cfg.set_nickname("U2", "  Tiny  ")   # trimmed
    assert roundtrip(cfg).nicknames == {"U1": "Boss", "U2": "Tiny"}
    cfg.set_nickname("U1", "")            # empty clears
    assert "U1" not in cfg.nicknames
    assert roundtrip(cfg).nicknames == {"U2": "Tiny"}


def test_dumps_then_loads_preserves_workspaces():
    cfg = Config(
        workspaces=[
            WorkspaceConfig(slug="acme", team_id="T1", theme="nord", order=2),
            WorkspaceConfig(slug="beta", team_id="T2"),
        ]
    )
    out = roundtrip(cfg)
    assert out.resolve_theme("T1") == "nord"
    assert out.slug_for("T1") == "acme"
    by_t1 = next(w for w in out.workspaces if w.team_id == "T1")
    assert by_t1.order == 2


def test_set_workspace_theme_persists_through_roundtrip():
    cfg = Config()
    cfg.set_workspace_theme("T9", "gruvbox-dark", slug="globex")
    out = roundtrip(cfg)
    assert out.resolve_theme("T9") == "gruvbox-dark"
