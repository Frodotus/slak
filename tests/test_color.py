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

from slak.color import ensure_contrast, lstar


def test_lstar_endpoints():
    assert lstar("#000000") == 0.0
    assert abs(lstar("#ffffff") - 100.0) < 0.01
    assert lstar("#808080") > 40  # mid grey is well above black


def test_ensure_contrast_raises_separation_for_close_pair():
    bg, surface = "#1a1b26", "#1f2233"  # the "dark" theme — only ~3.5 ΔL*
    fixed = ensure_contrast(bg, surface, target=6.0)
    assert abs(lstar(bg) - lstar(fixed)) >= 6.0


def test_ensure_contrast_leaves_sufficient_pairs_unchanged():
    bg, surface = "#1e1e2e", "#313244"  # catppuccin — already ~9.4 ΔL*
    assert ensure_contrast(bg, surface, target=6.0) == surface
