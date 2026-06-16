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

"""sRGB → CIELAB L* and the sidebar/message-pane contrast rule (spec 05 §contrast).

Dark themes must visually separate the sidebar (``surface``) from the message
pane (``bg``); :func:`ensure_contrast` nudges ``surface`` toward white/black
until ``|L*(bg) − L*(surface)| ≥ target``, so the guarantee holds for built-in
*and* user-supplied themes without hand-tuning palettes.
"""

from __future__ import annotations


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def lstar(hexcolor: str) -> float:
    """CIELAB lightness L* (0=black … 100=white) of an sRGB hex colour."""
    def linear(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hexcolor)
    y = 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
    f = y ** (1 / 3) if y > 0.008856 else 7.787 * y + 16 / 116
    return 116 * f - 16


def blend(a: str, b: str, t: float) -> str:
    """Linear sRGB blend: ``t=0`` → ``a``, ``t=1`` → ``b``."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def ensure_contrast(bg: str, surface: str, target: float = 6.0) -> str:
    """Return ``surface`` nudged so ``|L*(bg) − L*(surface)| ≥ target``.

    Already-separated pairs are returned unchanged. Otherwise the surface is
    blended toward white (if lighter than bg) or black, just enough to clear the
    threshold — preserving hue while improving separation.
    """
    lb = lstar(bg)
    if abs(lb - lstar(surface)) >= target:
        return surface
    toward = "#ffffff" if lstar(surface) >= lb else "#000000"
    candidate = surface
    for step in range(1, 101):
        candidate = blend(surface, toward, step / 100)
        if abs(lstar(candidate) - lb) >= target:
            break
    return candidate
