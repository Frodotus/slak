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

from slak.images import MediaImages, media_png


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
    assert mi.markup("http://x/a.png") is not None
    assert mi.markup("http://x/other.png") is None  # not transmitted


async def test_media_images_disabled_off_kitty():
    async def fetch(url):
        return a_png()

    mi = MediaImages("none", fetch, cache_dir="/tmp/slak-test-media2", emit=lambda s: None)
    assert await mi.ensure("http://x/a.png") is None
    assert mi.markup("http://x/a.png") is None
