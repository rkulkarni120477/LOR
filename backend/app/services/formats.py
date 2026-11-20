"""Bounded file inspection, text extraction and document preview conversion."""

import html
import io
import json
import logging
import re
import zipfile
from pathlib import PurePosixPath

from app.services.package_validation import (
    Limits,
    PackageReport,
    _parse_xml,
    _validate_pdf,
    _validate_zip,
)
from app.services.rich_text import plain_text

TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".zip": "application/zip",
    ".h5p": "application/zip",
}
MAX_TEXT = 500_000


def validate(filename: str, data: bytes, limits: Limits) -> PackageReport:
    ext = PurePosixPath(filename).suffix.lower()
    if ext == ".pdf":
        return _validate_pdf(data)
    if ext in {".zip", ".h5p", ".docx", ".pptx"}:
        report = _validate_zip(
            data,
            Limits(
                limits.max_entries,
                limits.max_uncompressed_bytes,
                limits.max_compression_ratio,
                True if ext != ".zip" else limits.allow_generic_zip,
            ),
        )
        if not report.valid:
            return report
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            required = {
                ".docx": ["word/document.xml"],
                ".pptx": ["ppt/presentation.xml"],
                ".h5p": ["h5p.json", "content/content.json"],
            }.get(ext, [])
            for path in required:
                if path not in archive.namelist():
                    report.errors.append(f"Missing {path}")
            if report.errors:
                return report
            if ext in {".docx", ".pptx"}:
                for path in required:
                    try:
                        _parse_xml(archive.read(path))
                    except Exception:
                        report.errors.append("Invalid Office XML")
                report.standard = "DOCX" if ext == ".docx" else "PPTX"
            elif ext == ".h5p":
                try:
                    manifest = json.loads(archive.read("h5p.json"))
                    json.loads(archive.read("content/content.json"))
                    if not manifest.get("mainLibrary"):
                        report.errors.append("H5P mainLibrary is required")
                    for dependency in manifest.get("preloadedDependencies", []):
                        library_path = (
                            f"{dependency['machineName']}-"
                            f"{dependency['majorVersion']}.{dependency['minorVersion']}/library.json"
                        )
                        if library_path not in archive.namelist():
                            report.errors.append(f"Missing bundled H5P dependency: {library_path}")
                    report.metadata["title"] = manifest.get("title")
                    report.standard = "H5P"
                except (ValueError, KeyError, TypeError):
                    report.errors.append("Invalid H5P JSON")
            elif not report.launch_files:
                report.launch_files = [
                    p for p in archive.namelist() if p.lower().endswith(("index.html", "index.htm"))
                ][:1]
        return report
    report = PackageReport(standard=ext.lstrip(".").upper())
    signatures = {
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".gif": data.startswith((b"GIF87a", b"GIF89a")),
        ".webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        ".mp4": data[4:8] == b"ftyp",
        ".mp3": data.startswith(b"ID3")
        or len(data) > 1
        and data[0] == 255
        and data[1] & 224 == 224,
    }
    if ext in signatures and not signatures[ext]:
        report.errors.append("File signature does not match its extension")
    if ext == ".svg":
        try:
            if not _parse_xml(data).tag.endswith("svg"):
                report.errors.append("Not an SVG document")
        except Exception:
            report.errors.append("Invalid SVG")
    if ext in {".html", ".htm"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            report.errors.append("HTML must use UTF-8 encoding")
    return report


def extract_text(filename: str, data: bytes) -> str:
    ext = PurePosixPath(filename).suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data), strict=False)
            return " ".join((page.extract_text() or "")[:50000] for page in reader.pages[:200])[
                :MAX_TEXT
            ]
        if ext in {".html", ".htm"}:
            return plain_text(data.decode("utf-8", "replace"))[:MAX_TEXT]
        if ext in {".docx", ".pptx", ".zip", ".h5p"}:
            parts = []
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                budget = 5_000_000
                for info in archive.infolist():
                    if info.file_size > min(budget, 1_000_000):
                        continue
                    name = info.filename
                    if (
                        ext == ".docx"
                        and name == "word/document.xml"
                        or ext == ".pptx"
                        and re.match(r"ppt/slides/slide\d+\.xml$", name)
                    ):
                        parts.append(" ".join(_parse_xml(archive.read(info)).itertext()))
                    elif ext in {".zip", ".h5p"} and name.endswith((".html", ".htm", ".json")):
                        parts.append(plain_text(archive.read(info).decode("utf-8", "replace")))
                    else:
                        continue
                    budget -= info.file_size
                    if budget <= 0:
                        break
            return " ".join(parts)[:MAX_TEXT]
    except Exception:
        logging.getLogger(__name__).warning("Text extraction unavailable", extra={"extension": ext})
    return ""


def office_preview(filename: str, data: bytes) -> str:
    """Text and images, without Office macros, external links, or active content."""
    import base64

    ext = PurePosixPath(filename).suffix.lower()
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = (
            ["word/document.xml"]
            if ext == ".docx"
            else sorted(
                [n for n in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
                key=lambda n: int(re.search(r"slide(\d+)", n).group(1)),
            )
        )
        for index, name in enumerate(names[:200]):
            root = _parse_xml(archive.read(name))
            paragraphs = [
                " ".join(n.itertext()) for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "p"
            ]
            out.append(
                f"<section><h2>{'Slide ' + str(index + 1) if ext == '.pptx' else 'Document'}</h2>"
                + "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
                + "</section>"
            )
        image_budget = 5_000_000
        for info in archive.infolist():
            mime = TYPES.get(PurePosixPath(info.filename).suffix.lower(), "")
            if (
                "/media/" in info.filename
                and mime in {"image/png", "image/jpeg", "image/gif", "image/webp"}
                and info.file_size < min(image_budget, 1_000_000)
            ):
                image_budget -= info.file_size
                encoded = base64.b64encode(archive.read(info)).decode()
                out.append(
                    '<img style="max-width:100%" alt="Embedded document image" '
                    f'src="data:{mime};base64,{encoded}">'
                )
    return "".join(out)
