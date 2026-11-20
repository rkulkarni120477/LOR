"""Thumbnails for stored packages.

If Pillow is installed and the package contains an image, the thumbnail is a PNG of that image,
scaled down. Otherwise a generated SVG card shows the standard and title. The SVG is built from
escaped text only, so it cannot carry script.
"""

import io
import posixpath
import zipfile
from html import escape

THUMB_SIZE = 320
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
PRIORITY_WORDS = ("thumb", "cover", "poster", "logo", "title")


def _embedded_image(data: bytes) -> bytes | None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    with archive:
        candidates = [
            i
            for i in archive.infolist()
            if not i.is_dir()
            and i.filename.lower().endswith(IMAGE_EXTENSIONS)
            and i.file_size <= 20 * 1024 * 1024
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda i: (
                not any(w in posixpath.basename(i.filename).lower() for w in PRIORITY_WORDS),
                i.filename,
            )
        )
        return archive.read(candidates[0])


def _scaled_png(image_bytes: bytes) -> bytes | None:
    try:
        from PIL import Image  # optional dependency
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.thumbnail((THUMB_SIZE, THUMB_SIZE))
            out = io.BytesIO()
            image.convert("RGBA").save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception:  # corrupt or unsupported image: fall back to the card
        return None


def _card(title: str, label: str) -> bytes:
    safe_title = escape(title[:60], quote=True)
    safe_label = escape(label[:40], quote=True)
    font = 'font-family="Arial, sans-serif" text-anchor="middle"'
    svg = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{THUMB_SIZE}" '
            f'height="{THUMB_SIZE}" viewBox="0 0 {THUMB_SIZE} {THUMB_SIZE}">',
            '  <rect width="100%" height="100%" fill="#eef3fb"/>',
            '  <rect x="24" y="24" width="272" height="272" rx="16" fill="#1762c4"/>',
            f'  <text x="160" y="150" {font} font-size="26" fill="#ffffff">{safe_label}</text>',
            f'  <text x="160" y="196" {font} font-size="16" fill="#dbe7fb">{safe_title}</text>',
            "</svg>",
        ]
    )
    return svg.encode("utf-8")


def make_thumbnail(data: bytes, title: str, standard: str | None) -> tuple[bytes, str]:
    """Returns (bytes, content_type) for the thumbnail."""
    image = _embedded_image(data)
    if image is not None:
        png = _scaled_png(image)
        if png is not None:
            return png, "image/png"
    return _card(title, standard or "Package"), "image/svg+xml"


THUMBNAIL_EXTENSIONS = {"image/png": "png", "image/svg+xml": "svg"}
