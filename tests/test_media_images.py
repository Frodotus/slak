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

import io

from PIL import Image

from slak.images import MediaImages, halfblock, media_png


def a_png(w=40, h=20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (10, 20, 30, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_media_png_returns_png_and_aspect_sized_footprint():
    png, cols, rows = media_png(a_png(40, 20), max_cols=24)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert cols == 24
    # 2:1 image in ~2.1-aspect cells → a few rows, never zero
    assert 1 <= rows <= 10


async def test_media_images_transmits_and_returns_placeholder():
    emitted = []

    async def fetch(url):
        return a_png()

    mi = MediaImages("kitty", fetch, cache_dir="/tmp/slak-test-media", emit=emitted.append)
    img_id = await mi.ensure("http://x/a.png")
    assert img_id is not None
    assert img_id >= 100_000  # high id range, no emoji collision
    assert emitted  # an upload sequence was emitted
    # the virtual placement must match the media footprint, not emoji 2x1
    _, cols, rows = media_png(a_png())
    assert f"c={cols},r={rows}" in emitted[0]
    assert cols > 2
    assert mi.markup("http://x/a.png") is not None
    assert mi.markup("http://x/other.png") is None  # not transmitted


async def test_media_images_ensure_honours_per_call_size_box():
    emitted = []

    async def fetch(url):
        return a_png(80, 40)  # 2:1 image

    mi = MediaImages("kitty", fetch, cache_dir="/tmp/slak-test-prevbox",
                     emit=emitted.append, max_cols=24, max_rows=10)
    await mi.ensure("http://x/big.png", max_cols=60, max_rows=40)
    assert "c=60" in emitted[0]  # placement uses the larger preview box, not 24


async def test_media_images_disabled_when_protocol_off():
    async def fetch(url):
        return a_png()

    mi = MediaImages("off", fetch, cache_dir="/tmp/slak-test-media2", emit=lambda s: None)
    assert await mi.ensure("http://x/a.png") is None
    assert mi.markup("http://x/a.png") is None


def a_red_png(w=4, h=4) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_avatar_placeholder_uses_the_same_color_as_the_name():
    from slak.ui.widgets import avatar_placeholder, user_color, AVATAR_COLS, AVATAR_ROWS
    p = avatar_placeholder("U777")
    rows = p.split("\n")
    assert len(rows) == AVATAR_ROWS
    assert all(f"on {user_color('U777')}" in r for r in rows)  # same hue as the name
    assert all(" " * AVATAR_COLS in r for r in rows)           # 4-cell block per row


def test_splitter_width_clamps_and_respects_side():
    from slak.ui.widgets import splitter_width
    # side 'left': target left of splitter, width = mouse - target_x
    assert splitter_width("left", target_x=0, target_right=26, mouse_x=30, lo=15, hi=80) == 30
    # side 'right': target right of splitter, width = target_right - mouse
    assert splitter_width("right", target_x=100, target_right=120, mouse_x=90, lo=15, hi=80) == 30
    # clamped to [lo, hi]
    assert splitter_width("left", 0, 10, 5, lo=15, hi=80) == 15    # below lo
    assert splitter_width("left", 0, 10, 999, lo=15, hi=80) == 80  # above hi


def test_rail_markup_is_a_single_horizontal_row():
    from slak.ui.widgets import _rail_markup
    out = _rail_markup(["AB", "CD", "EF"], active=1, unread=[False, False, True])
    assert "\n" not in out                 # horizontal: one row, no stacking
    assert "AB" in out and "CD" in out and "EF" in out
    assert "[b $text on $surface] CD [/]" in out  # active: bold on a lighter bg
    assert "●" in out                      # unread shows a dot
    # each tab is clickable -> switches to that workspace
    assert "@click=app.switch_workspace(0)" in out
    assert "@click=app.switch_workspace(2)" in out


def test_user_color_is_deterministic_and_spreads_across_palette():
    from slak.ui.widgets import user_color, _NAME_COLORS
    c = user_color("U123")
    assert c in _NAME_COLORS              # picked from the curated palette
    assert user_color("U123") == c        # deterministic for an id
    # many ids spread across most of the palette (good distinctness)
    colors = {user_color(f"U{i}") for i in range(200)}
    assert len(colors) >= len(_NAME_COLORS) - 2


def test_halfblock_emits_colored_upper_half_cells():
    out = halfblock(a_red_png(), cols=2, rows=1)
    assert "▀" in out
    assert "#ff0000" in out  # the solid-red pixels
    assert out.count("\n") == 0  # one row


async def test_media_images_halfblock_renders_inline_text_without_emit():
    emitted = []

    async def fetch(url):
        return a_red_png()

    mi = MediaImages("halfblock", fetch, cache_dir="/tmp/slak-test-hb", emit=emitted.append)
    assert mi.enabled
    assert await mi.ensure("http://x/a.png")
    assert not emitted  # halfblock is plain markup — nothing transmitted
    markup = mi.markup("http://x/a.png")
    assert markup is not None and "▀" in markup
