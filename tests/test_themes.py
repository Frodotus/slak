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

import copy

import slak.themes as themes_mod
from slak.color import lstar
from slak.themes import (
    SLOTS,
    get_theme,
    load_theme_files,
    theme_names,
    theme_variables,
)


def test_dark_is_available():
    assert "dark" in theme_names()
    assert len(theme_names()) >= 6


def test_oled_theme_has_true_black_background():
    assert "oled" in theme_names()
    assert get_theme("oled")["bg"] == "#000000"  # OLED pixels fully off


def test_every_theme_defines_every_slot():
    for name in theme_names():
        theme = get_theme(name)
        assert set(theme) == set(SLOTS), f"{name} missing slots"
        assert all(theme[s] for s in SLOTS)


def test_unknown_theme_falls_back_to_dark():
    assert get_theme("no-such-theme") == get_theme("dark")


def test_theme_variables_use_css_var_names():
    vars_ = theme_variables("dark")
    assert set(vars_) == {
        "accent",
        "bg",
        "hairline",
        "surface",
        "surface-dark",
        "text",
        "text-muted",
    }
    # values match the slot table (surface_dark slot -> "surface-dark" css var)
    assert vars_["surface-dark"] == get_theme("dark")["surface_dark"]


def test_theme_variables_enforce_sidebar_contrast():
    # every hex (non-ANSI) built-in's emitted surface separates from bg by >= 6 L*
    for name in theme_names():
        v = theme_variables(name)
        if not (v["bg"].startswith("#") and v["surface"].startswith("#")):
            continue  # ANSI-palette themes follow the terminal, exempt from contrast
        assert abs(lstar(v["bg"]) - lstar(v["surface"])) >= 6.0, name


def test_ansi_themes_use_ansi_palette_and_skip_contrast():
    for name in ("ansi-dark", "ansi-light"):
        assert name in theme_names()
        v = theme_variables(name)
        # values are ANSI palette names, untouched by the contrast nudge
        assert v["bg"] == "ansi_default"
        assert all(not val.startswith("#") for val in v.values())


def test_load_theme_files_registers_and_overrides(tmp_path):
    snapshot = copy.deepcopy(themes_mod.THEMES)
    try:
        (tmp_path / "mytheme.toml").write_text(
            "\n".join(f'{s} = "#101010"' for s in SLOTS)
        )
        (tmp_path / "dark.toml").write_text(
            "\n".join(f'{s} = "#abcdef"' for s in SLOTS)
        )
        n = load_theme_files(tmp_path)
        assert n == 2
        assert "mytheme" in theme_names()
        assert get_theme("dark")["accent"] == "#abcdef"  # built-in overridden
    finally:
        themes_mod.THEMES.clear()
        themes_mod.THEMES.update(snapshot)


def test_load_theme_files_missing_dir_is_zero(tmp_path):
    assert load_theme_files(tmp_path / "nope") == 0
