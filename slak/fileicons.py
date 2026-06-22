# slak — Terminal Slack client
# Copyright (C) 2026 Toni Leino
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generated colour file-type icons.

Rather than ship (or depend on) an external icon set, slak draws small document
tiles with Pillow — a category colour + short label — and renders them inline as
terminal images (kitty graphics, or ``▀`` half-blocks elsewhere). Self-contained,
licence-free, and works over SSH because it's just an image.
"""

from __future__ import annotations

import io

# category -> (label, fill RGB). Colours are chosen to read as the familiar
# app palette (PDF red, spreadsheet green, doc blue, …) without shipping logos.
_STYLE: dict[str, tuple[str, tuple[int, int, int]]] = {
    "pdf": ("PDF", (219, 68, 55)),
    "excel": ("XLS", (33, 160, 90)),
    "word": ("DOC", (43, 87, 154)),
    "ppt": ("PPT", (211, 96, 45)),
    "archive": ("ZIP", (150, 120, 60)),
    "image": ("IMG", (140, 90, 200)),
    "audio": ("AUD", (208, 95, 160)),
    "video": ("VID", (40, 150, 150)),
    "code": ("</>", (90, 105, 130)),
    "text": ("TXT", (110, 112, 122)),
    "other": ("FILE", (96, 100, 112)),
}

_CODE_EXTS = {"py", "js", "ts", "go", "rs", "c", "cpp", "h", "java", "rb", "sh",
              "json", "html", "css", "toml", "yaml", "yml", "xml"}
_ARCHIVE_EXTS = {"zip", "gz", "tar", "tgz", "rar", "7z", "bz2", "xz"}


def category_for(name: str = "", mimetype: str = "", filetype: str = "",
                 mode: str = "") -> str:
    """Coarse file category driving the icon/colour and the glyph fallback."""
    mt = (mimetype or "").lower()
    ext = (filetype or "").lower()
    if not ext and "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("xls", "xlsx", "csv") or "spreadsheet" in mt:
        return "excel"
    if ext in ("doc", "docx", "rtf") or "wordprocessing" in mt:
        return "word"
    if ext in ("ppt", "pptx") or "presentation" in mt:
        return "ppt"
    if ext == "pdf" or mt == "application/pdf":
        return "pdf"
    if mt.startswith("image/"):
        return "image"
    if mt.startswith("video/"):
        return "video"
    if mt.startswith("audio/"):
        return "audio"
    if ext in _ARCHIVE_EXTS or "zip" in mt or "compressed" in mt:
        return "archive"
    if mode == "snippet" or ext in _CODE_EXTS:
        return "code"
    if mt.startswith("text/"):
        return "text"
    return "other"


def icon_png(category: str, size: int = 64) -> bytes:
    """A document-tile PNG for ``category``: rounded body in the category colour,
    a folded top-right corner, and a short white label (legible on kitty)."""
    from PIL import Image, ImageDraw, ImageFont

    label, color = _STYLE.get(category, _STYLE["other"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 8
    fold = size // 3
    left, top, right, bottom = pad, pad, size - pad, size - pad
    # document body with a clipped (folded) top-right corner
    d.polygon(
        [(left, top), (right - fold, top), (right, top + fold),
         (right, bottom), (left, bottom)],
        fill=color,
    )
    d.polygon([(right - fold, top), (right, top + fold),
               (right - fold, top + fold)], fill=(255, 255, 255, 90))
    try:
        font = ImageFont.load_default(size=size // 4)
    except TypeError:  # very old Pillow without the size arg
        font = ImageFont.load_default()
    d.text((size / 2, bottom - size // 5), label, fill="white",
           font=font, anchor="mm")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
