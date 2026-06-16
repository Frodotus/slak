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

from slak.themes import SLOTS, get_theme, theme_names, theme_variables


def test_dark_is_available():
    assert "dark" in theme_names()
    assert len(theme_names()) >= 6


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
