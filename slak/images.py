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

"""Terminal image support — capability detection and the kitty graphics encoder.

The kitty graphics protocol lets capable terminals (kitty, Ghostty, WezTerm)
display inline PNGs, which is how custom emoji are rendered. Detection and the
escape-sequence encoding are pure and tested here; the live transmission into a
running Textual screen is environment-dependent.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path

_KITTY_TERMS = ("kitty", "ghostty", "wezterm")


def detect_protocol(env: dict[str, str]) -> str:
    """Return the best inline-image protocol for the environment.

    One of "kitty", "sixel", "halfblock", or "off".
    """
    term = env.get("TERM", "").lower()
    term_program = env.get("TERM_PROGRAM", "").lower()
    if env.get("KITTY_WINDOW_ID") or "kitty" in term or term_program in _KITTY_TERMS:
        return "kitty"
    if "foot" in term or env.get("WEZTERM_PANE"):
        return "sixel"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "halfblock"
    return "off"


def kitty_inline(png: bytes, cols: int, rows: int) -> str:
    """Encode PNG bytes as a kitty graphics escape that displays inline.

    Transmits and displays (a=T) a PNG (f=100) occupying ``cols``×``rows`` cells.
    Suitable for small images such as emoji (single, unchunked payload).
    """
    payload = base64.b64encode(png).decode("ascii")
    return f"\x1b_Ga=T,f=100,c={cols},r={rows};{payload}\x1b\\"


# Kitty's Unicode placeholder char and the row/column diacritics (prefix of
# kitty's rowcolumn-diacritics table — enough for emoji-sized placements).
_PLACEHOLDER = "\U0010EEEE"
_DIACRITICS = [
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F, 0x0346, 0x034A,
    0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357, 0x035B, 0x0363, 0x0364, 0x0365,
    0x0366, 0x0367, 0x0368, 0x0369, 0x036A, 0x036B, 0x036C, 0x036D, 0x036E, 0x036F,
    0x0483, 0x0484, 0x0485, 0x0486, 0x0487, 0x0592, 0x0593, 0x0594, 0x0595, 0x0597,
]


def tmux_passthrough(seq: str) -> str:
    """Wrap an escape sequence so tmux forwards it to the outer terminal.

    Requires ``set -g allow-passthrough on`` in the user's tmux config.
    """
    return "\x1bPtmux;" + seq.replace("\x1b", "\x1b\x1b") + "\x1b\\"


def kitty_transmit(
    image_id: int, png: bytes, cols: int = 2, rows: int = 1, chunk: int = 4096
) -> str:
    """Transmit a PNG and create a virtual placement for Unicode placeholders.

    ``a=T,U=1`` transmits the PNG (f=100) under ``image_id`` and creates a virtual
    placement sized ``cols``×``rows`` cells; placeholder cells then reference it.
    Large payloads are split into ``m=1`` continuation chunks + an ``m=0`` final.
    """
    payload = base64.b64encode(png).decode("ascii")
    head = f"a=T,f=100,t=d,U=1,i={image_id},c={cols},r={rows},q=2"
    if len(payload) <= chunk:
        return f"\x1b_G{head};{payload}\x1b\\"
    parts = [payload[i : i + chunk] for i in range(0, len(payload), chunk)]
    out = []
    for idx, part in enumerate(parts):
        last = idx == len(parts) - 1
        m = 0 if last else 1
        if idx == 0:
            out.append(f"\x1b_G{head},m={m};{part}\x1b\\")
        else:
            out.append(f"\x1b_Gm={m};{part}\x1b\\")
    return "".join(out)


def kitty_placeholder_markup(image_id: int, cols: int = 2, rows: int = 1) -> str:
    """Rich markup that places ``image_id`` over ``cols``×``rows`` cells.

    Each cell is the placeholder char + row/column diacritics; the foreground
    colour carries the low 24 bits of the image id (kitty reads it back).
    """
    color = f"#{image_id & 0xFFFFFF:06x}"
    rows_text = []
    for r in range(rows):
        cells = "".join(
            _PLACEHOLDER + chr(_DIACRITICS[r]) + chr(_DIACRITICS[c])
            for c in range(cols)
        )
        rows_text.append(cells)
    return f"[{color}]" + "\n".join(rows_text) + "[/]"


class ImageCache:
    """Async image fetcher with in-memory + on-disk caching and singleflight.

    ``fetch`` is injectable (real HTTP, or a fake in tests). Each URL is fetched
    at most once; bytes persist under ``cache_dir`` keyed by a hash of the URL.
    """

    def __init__(self, fetch: Callable[[str], Awaitable[bytes]], cache_dir):
        self._fetch = fetch
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, bytes] = {}
        self._inflight: dict[str, asyncio.Future] = {}

    def _path(self, url: str) -> Path:
        return self._dir / (hashlib.sha256(url.encode()).hexdigest() + ".img")

    async def get(self, url: str) -> bytes:
        if url in self._mem:
            return self._mem[url]
        path = self._path(url)
        if path.exists():
            data = path.read_bytes()
            self._mem[url] = data
            return data
        if url in self._inflight:
            return await self._inflight[url]
        fut = asyncio.ensure_future(self._fetch_store(url, path))
        self._inflight[url] = fut
        try:
            return await fut
        finally:
            self._inflight.pop(url, None)

    async def _fetch_store(self, url: str, path: Path) -> bytes:
        data = await self._fetch(url)
        path.write_bytes(data)
        self._mem[url] = data
        return data


def emoji_png(data: bytes, size: int = 48) -> bytes:
    """Normalise emoji image bytes to a small PNG.

    Takes the first frame (so animated GIFs become a static PNG kitty accepts),
    converts to RGBA, downscales to ``size`` px, and re-encodes as PNG — which
    also keeps the payload small enough to transmit in a single chunk.
    """
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    try:
        img.seek(0)  # first frame of an animation
    except (EOFError, ValueError):
        pass
    img = img.convert("RGBA")
    img.thumbnail((size, size))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class EmojiImages:
    """Manages kitty image transmission for custom emoji (best-effort, kitty-only).

    On a kitty-class terminal it fetches each emoji PNG (cached), transmits it
    under a stable image id via ``emit`` (raw terminal write), and hands back the
    placeholder markup to drop into message text. Disabled (no-op) elsewhere.
    """

    def __init__(self, protocol: str, fetch, cache_dir, emit):
        self.enabled = protocol == "kitty"
        self._cache = ImageCache(fetch, cache_dir)
        self._emit = emit
        self._ids: dict[str, int] = {}
        self._ready: set[str] = set()
        self._next = 1

    async def ensure(self, url: str) -> int | None:
        if not self.enabled or not url:
            return None
        if url in self._ready:
            return self._ids[url]
        try:
            raw = await self._cache.get(url)
            png = emoji_png(raw)
        except Exception:
            return None
        img_id = self._ids.get(url)
        if img_id is None:
            img_id = self._next
            self._ids[url] = img_id
            self._next += 1
        try:
            self._emit(kitty_transmit(img_id, png))
        except Exception:
            return None
        self._ready.add(url)
        return img_id

    def markup(self, url: str) -> str | None:
        if url in self._ready:
            return kitty_placeholder_markup(self._ids[url])
        return None
