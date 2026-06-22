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

from slak.config import Config

SAMPLE = """
[general]
default_workspace = "work"
use_slack_sections = true

[appearance]
theme = "nord"
group_within_minutes = 5

[theme]
accent = "#FF8800"

[workspaces.work]
team_id = "T01WORK"
theme = "dracula"
order = 1

[workspaces.side]
team_id = "T02SIDE"
order = 2

[workspaces.archived]
team_id = "T03ARCH"
"""


def test_loads_parses_general_and_appearance():
    cfg = Config.loads(SAMPLE)
    assert cfg.default_workspace == "work"
    assert cfg.theme == "nord"
    assert cfg.use_slack_sections is True
    assert cfg.group_within_minutes == 5
    assert cfg.theme_overrides == {"accent": "#FF8800"}


def test_resolve_theme_prefers_per_workspace():
    cfg = Config.loads(SAMPLE)
    assert cfg.resolve_theme("T01WORK") == "dracula"


def test_resolve_theme_falls_back_to_global_appearance():
    cfg = Config.loads(SAMPLE)
    assert cfg.resolve_theme("T02SIDE") == "nord"


def test_resolve_theme_defaults_to_dark_when_unknown_and_no_global():
    cfg = Config.loads("")
    assert cfg.resolve_theme("T99NONE") == "dark"


def test_slug_for_team_id():
    cfg = Config.loads(SAMPLE)
    assert cfg.slug_for("T02SIDE") == "side"
    assert cfg.slug_for("T0UNKNOWN") is None


def test_order_team_ids_orders_then_alpha_then_unconfigured():
    cfg = Config.loads(SAMPLE)
    # Includes an unconfigured workspace T04EXTRA present in tokens.
    ordered = cfg.order_team_ids(["T03ARCH", "T02SIDE", "T01WORK", "T04EXTRA"])
    # A: order>0 ascending -> work(1), side(2)
    # B: configured w/o order, by slug -> archived
    # C: unconfigured by team_id -> T04EXTRA
    assert ordered == ["T01WORK", "T02SIDE", "T03ARCH", "T04EXTRA"]


def test_order_ties_broken_by_slug():
    toml = """
[workspaces.zeta]
team_id = "TZ"
order = 1
[workspaces.alpha]
team_id = "TA"
order = 1
"""
    cfg = Config.loads(toml)
    assert cfg.order_team_ids(["TZ", "TA"]) == ["TA", "TZ"]


def test_legacy_team_id_keyed_block():
    # A block keyed directly by team id (no team_id field) still works.
    toml = """
[workspaces.T0LEGACY1]
theme = "gruvbox"
"""
    cfg = Config.loads(toml)
    assert cfg.resolve_theme("T0LEGACY1") == "gruvbox"
    assert cfg.slug_for("T0LEGACY1") == "T0LEGACY1"


def test_slugify_basic():
    from slak.config import slugify
    assert slugify("Acme Corp", set()) == "acme-corp"


def test_slugify_strips_punctuation_and_edges():
    from slak.config import slugify
    assert slugify("  Acme!! Corp.  ", set()) == "acme-corp"


def test_slugify_dedupes_with_numeric_suffix():
    from slak.config import slugify
    assert slugify("Acme", {"acme"}) == "acme-2"
    assert slugify("Acme", {"acme", "acme-2"}) == "acme-3"


def test_notifications_defaults():
    cfg = Config.loads("")
    assert cfg.notify_enabled is True
    assert cfg.notify_on_mention is True
    assert cfg.notify_on_dm is True
    assert cfg.notify_keywords == []


def test_notifications_parsed():
    cfg = Config.loads('''
[notifications]
enabled = true
on_mention = false
on_dm = true
on_keyword = ["deploy", "incident"]
''')
    assert cfg.notify_on_mention is False
    assert cfg.notify_keywords == ["deploy", "incident"]


def test_image_protocol_default_auto():
    assert Config.loads("").image_protocol == "auto"


def test_image_protocol_parsed():
    cfg = Config.loads('[appearance]\nimage_protocol = "kitty"')
    assert cfg.image_protocol == "kitty"


def test_emoji_images_default_on():
    assert Config.loads("").emoji_images is True


def test_emoji_images_parsed_bool_or_legacy_string():
    assert Config.loads('[appearance]\nemoji_images = false').emoji_images is False
    assert Config.loads('[appearance]\nemoji_images = "off"').emoji_images is False  # legacy
