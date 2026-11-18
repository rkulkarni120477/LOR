"""Extract text and manifest data from SCORM / zip packages. Reads entries only; never extracts
to disk, and caps the bytes read per entry to limit zip-bomb impact."""

import io
import re
import zipfile
from dataclasses import dataclass, field

MAX_ENTRY_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = (".html", ".htm", ".xhtml", ".txt", ".md")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov")
CAPTION_EXTENSIONS = (".vtt", ".srt")
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ALT_RE = re.compile(r"\balt\s*=\s*\"([^\"]*)\"", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_MANIFEST_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LICENSE_RE = re.compile(r"<license[^>]*>(.*?)</license>", re.IGNORECASE | re.DOTALL)


@dataclass
class PackageInfo:
    file_names: list[str] = field(default_factory=list)
    manifest_title: str | None = None
    manifest_license: str | None = None
    text_excerpt: str = ""
    img_count: int = 0
    img_with_alt: int = 0
    has_video: bool = False
    has_captions: bool = False
    is_valid_zip: bool = True


def parse_package(data: bytes, excerpt_chars: int = 4000) -> PackageInfo:
    info = PackageInfo()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        info.is_valid_zip = False
        return info

    text_parts: list[str] = []
    with archive:
        names = archive.namelist()
        info.file_names = names
        lowered = [n.lower() for n in names]
        info.has_video = any(n.endswith(VIDEO_EXTENSIONS) for n in lowered)
        info.has_captions = any(n.endswith(CAPTION_EXTENSIONS) for n in lowered)

        for name in names:
            lname = name.lower()
            if lname.endswith("imsmanifest.xml") or lname.endswith("imsmanifest.xml".upper()):
                manifest = _read_text(archive, name)
                title = _MANIFEST_TITLE_RE.search(manifest)
                lic = _LICENSE_RE.search(manifest)
                info.manifest_title = title.group(1).strip() if title else None
                info.manifest_license = lic.group(1).strip() if lic else None
            elif lname.endswith(TEXT_EXTENSIONS):
                html = _read_text(archive, name)
                for img in _IMG_RE.findall(html):
                    info.img_count += 1
                    alt = _ALT_RE.search(img)
                    if alt and alt.group(1).strip():
                        info.img_with_alt += 1
                title = _TITLE_RE.search(html)
                if title and not info.manifest_title:
                    info.manifest_title = title.group(1).strip()
                text_parts.append(_TAG_RE.sub(" ", html))

    text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
    info.text_excerpt = text[:excerpt_chars]
    return info


def _read_text(archive: zipfile.ZipFile, name: str) -> str:
    with archive.open(name) as handle:
        raw = handle.read(MAX_ENTRY_BYTES)
    return raw.decode("utf-8", errors="replace")
