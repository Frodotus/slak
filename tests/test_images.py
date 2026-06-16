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

import base64

from slak.images import detect_protocol, kitty_inline, kitty_transmit


def test_detect_protocol_kitty():
    assert detect_protocol({"KITTY_WINDOW_ID": "1"}) == "kitty"
    assert detect_protocol({"TERM": "xterm-kitty"}) == "kitty"
    assert detect_protocol({"TERM_PROGRAM": "ghostty"}) == "kitty"


def test_detect_protocol_non_kitty():
    assert detect_protocol({"TERM": "xterm-256color"}) in ("halfblock", "off", "sixel")


def test_kitty_inline_encodes_png_payload():
    png = b"\x89PNG\r\n\x1a\nDATA"
    seq = kitty_inline(png, cols=2, rows=1)
    assert seq.startswith("\x1b_G")
    assert seq.endswith("\x1b\\")
    assert "f=100" in seq and "c=2" in seq and "r=1" in seq
    assert base64.b64encode(png).decode() in seq


async def test_image_cache_fetches_once_then_memoises(tmp_path):
    from slak.images import ImageCache
    calls = []

    async def fetch(url):
        calls.append(url)
        return b"PNGDATA"

    cache = ImageCache(fetch, tmp_path)
    assert await cache.get("http://x/a.png") == b"PNGDATA"
    assert await cache.get("http://x/a.png") == b"PNGDATA"
    assert len(calls) == 1


async def test_image_cache_persists_to_disk(tmp_path):
    from slak.images import ImageCache

    async def fetch(url):
        return b"PNGDATA"

    await ImageCache(fetch, tmp_path).get("http://x/a.png")

    calls = []

    async def fetch2(url):
        calls.append(url)
        return b"OTHER"

    fresh = ImageCache(fetch2, tmp_path)
    assert await fresh.get("http://x/a.png") == b"PNGDATA"  # loaded from disk
    assert calls == []


def test_kitty_transmit_single_chunk():
    s = kitty_transmit(5, b"PNGDATA", cols=2, rows=1)
    assert s.startswith("\x1b_G")
    assert s.endswith("\x1b\\")
    for token in ("a=T", "U=1", "f=100", "i=5", "c=2", "r=1"):
        assert token in s
    assert base64.b64encode(b"PNGDATA").decode() in s


def test_kitty_transmit_chunks_large_payload():
    s = kitty_transmit(1, b"x" * 10000, chunk=4096)
    assert s.count("\x1b_G") >= 3      # split across multiple APC escapes
    assert "m=1" in s and "m=0" in s   # continuation + final markers


def test_kitty_placeholder_markup():
    from slak.images import kitty_placeholder_markup
    m = kitty_placeholder_markup(0x0000FF, cols=2, rows=1)
    assert "#0000ff" in m              # fg colour encodes the image id
    assert m.count("\U0010EEEE") == 2  # one placeholder per cell


def test_tmux_passthrough_wraps_and_doubles_escapes():
    from slak.images import tmux_passthrough
    out = tmux_passthrough("\x1b_Gx;y\x1b\\")
    assert out.startswith("\x1bPtmux;")
    assert out.endswith("\x1b\\")
    assert "\x1b\x1b_Gx;y" in out  # inner ESCs doubled


def test_emoji_png_resizes_to_small_png():
    import io

    from PIL import Image

    from slak.images import emoji_png
    buf = io.BytesIO()
    Image.new("RGBA", (128, 128), (255, 0, 0, 255)).save(buf, format="PNG")
    out = emoji_png(buf.getvalue(), size=32)
    assert out[:4] == b"\x89PNG"
    assert max(Image.open(io.BytesIO(out)).size) <= 32


def test_emoji_png_converts_gif_first_frame():
    import io

    from PIL import Image

    from slak.images import emoji_png
    buf = io.BytesIO()
    Image.new("P", (64, 64)).save(buf, format="GIF")
    out = emoji_png(buf.getvalue(), size=32)
    assert out[:4] == b"\x89PNG"  # GIF -> PNG
