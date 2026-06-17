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


# Kitty's Unicode placeholder char and the FULL row/column diacritics table (297
# codepoints, kitty's canonical rowcolumn-diacritics order). The full table is
# required so large placements (e.g. a full-screen image preview) can address
# every row/column — a truncated prefix overflows and crashes.
_PLACEHOLDER = "\U0010EEEE"
_DIACRITICS = [int(h, 16) for h in (
    "0305 030D 030E 0310 0312 033D 033E 033F 0346 034A 034B 034C 0350 0351 0352 "
    "0357 035B 0363 0364 0365 0366 0367 0368 0369 036A 036B 036C 036D 036E 036F "
    "0483 0484 0485 0486 0487 0592 0593 0594 0595 0597 0598 0599 059C 059D 059E "
    "059F 05A0 05A1 05A8 05A9 05AB 05AC 05AF 05C4 0610 0611 0612 0613 0614 0615 "
    "0616 0617 0657 0658 0659 065A 065B 065D 065E 06D6 06D7 06D8 06D9 06DA 06DB "
    "06DC 06DF 06E0 06E1 06E2 06E4 06E7 06E8 06EB 06EC 0730 0732 0733 0735 0736 "
    "073A 073D 073F 0740 0741 0743 0745 0747 0749 074A 07EB 07EC 07ED 07EE 07EF "
    "07F0 07F1 07F3 0816 0817 0818 0819 081B 081C 081D 081E 081F 0820 0821 0822 "
    "0823 0825 0826 0827 0829 082A 082B 082C 082D 0951 0953 0954 0F82 0F83 0F86 "
    "0F87 135D 135E 135F 17DD 193A 1A17 1A75 1A76 1A77 1A78 1A79 1A7A 1A7B 1A7C "
    "1B6B 1B6D 1B6E 1B6F 1B70 1B71 1B72 1B73 1CD0 1CD1 1CD2 1CDA 1CDB 1CE0 1DC0 "
    "1DC1 1DC3 1DC4 1DC5 1DC6 1DC7 1DC8 1DC9 1DCB 1DCC 1DD1 1DD2 1DD3 1DD4 1DD5 "
    "1DD6 1DD7 1DD8 1DD9 1DDA 1DDB 1DDC 1DDD 1DDE 1DDF 1DE0 1DE1 1DE2 1DE3 1DE4 "
    "1DE5 1DE6 1DFE 20D0 20D1 20D4 20D5 20D6 20D7 20DB 20DC 20E1 20E7 20E9 20F0 "
    "2CEF 2CF0 2CF1 2DE0 2DE1 2DE2 2DE3 2DE4 2DE5 2DE6 2DE7 2DE8 2DE9 2DEA 2DEB "
    "2DEC 2DED 2DEE 2DEF 2DF0 2DF1 2DF2 2DF3 2DF4 2DF5 2DF6 2DF7 2DF8 2DF9 2DFA "
    "2DFB 2DFC 2DFD 2DFE 2DFF A66F A67C A67D A6F0 A6F1 A8E0 A8E1 A8E2 A8E3 A8E4 "
    "A8E5 A8E6 A8E7 A8E8 A8E9 A8EA A8EB A8EC A8ED A8EE A8EF A8F0 A8F1 AAB0 AAB2 "
    "AAB3 AAB7 AAB8 AABE AABF AAC1 FE20 FE21 FE22 FE23 FE24 FE25 FE26 10A0F 10A38 "
    "1D185 1D186 1D187 1D188 1D189 1D1AA 1D1AB 1D1AC 1D1AD 1D242 1D243 1D244 "
).split()]


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
    # Wrap EACH row in its own colour span (not one span across all rows), so the
    # markup survives being split on newlines and interleaved with other text —
    # e.g. the avatar gutter prefixes each row onto a different message line.
    rows_text = []
    for r in range(rows):
        cells = "".join(
            _PLACEHOLDER + chr(_DIACRITICS[r]) + chr(_DIACRITICS[c])
            for c in range(cols)
        )
        rows_text.append(f"[{color}]{cells}[/]")
    return "\n".join(rows_text)


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


def _fit_cells(w: int, h: int, max_cols: int, max_rows: int,
               cell_aspect: float = 2.1) -> tuple[int, int]:
    """Cell footprint preserving aspect (cells ~``cell_aspect``× taller), capped."""
    cols = max_cols
    rows = max(1, round(cols * (h / w) / cell_aspect))
    if rows > max_rows:
        rows = max_rows
        cols = max(1, round(rows * (w / h) * cell_aspect))
    return cols, rows


def _first_frame(data: bytes, mode: str = "RGBA"):
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    try:
        img.seek(0)  # first frame of an animation
    except (EOFError, ValueError):
        pass
    return img.convert(mode)


def media_png(data: bytes, max_cols: int = 24, max_rows: int = 10,
              cell_aspect: float = 2.1) -> tuple[bytes, int, int]:
    """Normalise an attachment/block image to a PNG plus its cell footprint.

    Returns ``(png, cols, rows)`` where cols×rows preserves the image's aspect,
    capped to the max box; the PNG is downscaled to keep the payload small.
    """
    import io

    img = _first_frame(data)
    cols, rows = _fit_cells(*img.size, max_cols, max_rows, cell_aspect)
    img.thumbnail((cols * 14, rows * 30))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), cols, rows


def halfblock(data: bytes, cols: int, rows: int) -> str:
    """Render an image as Rich markup using ``▀`` half-block cells.

    Each cell packs two vertical pixels: the upper pixel becomes the glyph's
    foreground, the lower its background. Works on any truecolor terminal — no
    image protocol required.
    """
    img = _first_frame(data, "RGB").resize((cols, rows * 2))
    px = img.load()

    def hexc(c) -> str:
        return "#{:02x}{:02x}{:02x}".format(*c[:3])

    lines = []
    for r in range(rows):
        cells = [
            f"[{hexc(px[c, 2 * r])} on {hexc(px[c, 2 * r + 1])}]▀[/]"
            for c in range(cols)
        ]
        lines.append("".join(cells))
    return "\n".join(lines)


class MediaImages:
    """Inline rendering for attachment/block images.

    On **kitty** it transmits each image under a high-based image id (so ids never
    collide with emoji) and hands back placeholder markup. On a truecolor terminal
    (**halfblock**) it renders ``▀`` cells inline — no protocol needed. Disabled
    (no-op) otherwise.
    """

    def __init__(self, protocol: str, fetch, cache_dir, emit,
                 id_base: int = 100_000, max_cols: int = 24, max_rows: int = 10):
        self.enabled = protocol in ("kitty", "halfblock")
        self._protocol = protocol
        self._cache = ImageCache(fetch, cache_dir)
        self._emit = emit
        self._markup: dict[str, str] = {}  # url -> ready placeholder/halfblock markup
        self._ready: set[str] = set()
        self._next = id_base
        self._max_cols = max_cols
        self._max_rows = max_rows

    async def ensure(self, url: str, max_cols: int | None = None,
                     max_rows: int | None = None):
        if not self.enabled or not url:
            return None
        if url in self._ready:
            return True
        try:
            raw = await self._cache.get(url)
        except Exception:
            return None
        cap_cols = max_cols or self._max_cols
        cap_rows = max_rows or self._max_rows
        if self._protocol == "kitty":
            return await self._ensure_kitty(url, raw, cap_cols, cap_rows)
        try:
            cols, rows = _fit_cells(*_first_frame(raw).size, cap_cols, cap_rows)
            self._markup[url] = halfblock(raw, cols, rows)
        except Exception:
            return None
        self._ready.add(url)
        return True

    async def _ensure_kitty(self, url: str, raw: bytes,
                            cap_cols: int, cap_rows: int):
        try:
            png, cols, rows = media_png(raw, cap_cols, cap_rows)
        except Exception:
            return None
        img_id = self._next
        self._next += 1
        try:
            # virtual placement must match the placeholder footprint (cols×rows),
            # otherwise the image is crammed into the 2×1 emoji default
            self._emit(kitty_transmit(img_id, png, cols, rows))
        except Exception:
            return None
        self._markup[url] = kitty_placeholder_markup(img_id, cols, rows)
        self._ready.add(url)
        return img_id

    def markup(self, url: str) -> str | None:
        return self._markup.get(url)


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
