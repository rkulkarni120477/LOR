"""Package validation for uploads: SCORM 1.2 / 2004, cmi5, xAPI (Tin Can) and PDF.

Pure functions over bytes. Nothing is extracted to disk. A package with errors is rejected by the
caller. Warnings are kept with the stored version so reviewers can see them.
"""

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

PDF_STANDARD = "PDF"
GENERIC_STANDARD = "generic web package"
_XML_UNSAFE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


@dataclass
class PackageReport:
    standard: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    launch_files: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "standard": self.standard,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "launch_files": self.launch_files,
        }


@dataclass
class Limits:
    max_entries: int = 10_000
    max_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_compression_ratio: int = 100
    allow_generic_zip: bool = True


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _attrs(element: ET.Element) -> dict[str, str]:
    return {_local(k): v for k, v in element.attrib.items()}


def _children(element: ET.Element, name: str):
    return [c for c in element.iter() if _local(c.tag) == name]


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _parse_xml(data: bytes) -> ET.Element:
    # DTDs and entity declarations are the usual vehicle for billion-laughs and external entity
    # attacks. Packages have no legitimate need for them, so they are refused outright.
    if _XML_UNSAFE.search(data):
        raise ValueError("DTD or entity declarations are not allowed")
    return ET.fromstring(data)


def _normalize(href: str) -> str | None:
    """Returns a safe, archive-relative path for an href, or None if it escapes the package."""
    path = unquote(urlsplit(href.strip()).path).replace("\\", "/")
    if not path or path.startswith("/") or "\x00" in path:
        return None
    if re.match(r"^[A-Za-z]:", path):
        return None
    normalized = posixpath.normpath(path)
    if normalized.startswith("..") or normalized == "." or "/../" in f"/{normalized}/":
        return None
    return normalized


class _Archive:
    def __init__(self, names: list[str]) -> None:
        self.names = set(names)
        self.lower = {n.lower(): n for n in names}

    def find(self, path: str) -> str | None:
        return self.lower.get(path.lower())

    def has_href(self, href: str) -> tuple[bool, str | None]:
        """Returns (is_remote, normalized_path). Remote launch URLs are not checked."""
        parts = urlsplit(href.strip())
        if parts.scheme in {"http", "https"}:
            return True, None
        return False, _normalize(href)


def validate(filename: str, data: bytes, limits: Limits | None = None) -> PackageReport:
    limits = limits or Limits()
    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        return _validate_pdf(data)
    return _validate_zip(data, limits)


# --- PDF ---------------------------------------------------------------------


def _validate_pdf(data: bytes) -> PackageReport:
    report = PackageReport(standard=PDF_STANDARD)
    if data[:5] != b"%PDF-":
        report.errors.append("file does not start with a PDF header")
        return report
    if b"%%EOF" not in data[-2048:]:
        report.errors.append("PDF has no end-of-file marker; the file may be truncated")
    head = data[:2_000_000]
    title = re.search(rb"/Title\s*\(([^)]{0,500})\)", head)
    author = re.search(rb"/Author\s*\(([^)]{0,500})\)", head)
    pages = len(re.findall(rb"/Type\s*/Page(?!s)\b", head))
    report.metadata = {
        "title": title.group(1).decode("latin-1", "replace") if title else None,
        "author": author.group(1).decode("latin-1", "replace") if author else None,
        "page_count": pages or None,
    }
    if b"/Encrypt" in data[-4096:]:
        report.warnings.append("PDF is encrypted; text metadata may be incomplete")
    return report


# --- ZIP-based packages ------------------------------------------------------


def _validate_zip(data: bytes, limits: Limits) -> PackageReport:
    report = PackageReport()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        report.errors.append("not a valid zip archive")
        return report
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            report.errors.append(f"package has more than {limits.max_entries} entries")
            return report
        total = sum(i.file_size for i in infos)
        compressed = sum(i.compress_size for i in infos)
        if total > limits.max_uncompressed_bytes:
            report.errors.append("package expands beyond the allowed size")
            return report
        if compressed and total // max(compressed, 1) > limits.max_compression_ratio:
            report.errors.append("suspicious compression ratio (possible zip bomb)")
            return report
        names = []
        for info in infos:
            if info.is_dir():
                continue
            if _normalize(info.filename) is None:
                report.errors.append(f"unsafe path in package: {info.filename!r}")
                return report
            names.append(info.filename)
        if report.errors:
            return report
        index = _Archive(names)
        manifest_names = {n.lower() for n in names if "/" not in n}
        if "cmi5.xml" in manifest_names:
            _validate_cmi5(archive, index, report)
        elif "imsmanifest.xml" in manifest_names:
            _validate_scorm(archive, index, report)
        elif "tincan.xml" in manifest_names:
            _validate_xapi(archive, index, report)
        else:
            report.standard = GENERIC_STANDARD
            if not limits.allow_generic_zip:
                report.errors.append("package has no SCORM, cmi5 or xAPI manifest")
            else:
                report.warnings.append(
                    "no SCORM, cmi5 or xAPI manifest; stored as generic web content"
                )
        return report


def _read_xml(archive: zipfile.ZipFile, index: _Archive, name: str, report: PackageReport):
    real = index.find(name)
    try:
        return _parse_xml(archive.read(real))
    except (ValueError, ET.ParseError) as exc:
        report.errors.append(f"{name} is not valid XML: {exc}")
        return None


def _check_file(index: _Archive, href: str, report: PackageReport, what: str) -> str | None:
    remote, path = index.has_href(href)
    if remote:
        report.warnings.append(f"{what} points to an external URL: {href}")
        return None
    if path is None:
        report.errors.append(f"{what} has an unsafe path: {href!r}")
        return None
    real = index.find(path)
    if real is None:
        report.errors.append(f"{what} refers to a missing file: {href}")
        return None
    return real


# --- SCORM -------------------------------------------------------------------


def _validate_scorm(archive: zipfile.ZipFile, index: _Archive, report: PackageReport) -> None:
    root = _read_xml(archive, index, "imsmanifest.xml", report)
    if root is None:
        return
    if _local(root.tag) != "manifest":
        report.errors.append("imsmanifest.xml root element must be <manifest>")
        return
    version_el = next((c for c in root.iter() if _local(c.tag) == "schemaversion"), None)
    version = _text(version_el)
    if version == "1.2":
        report.standard = "SCORM 1.2"
    elif version.startswith("2004"):
        report.standard = "SCORM 2004"
    else:
        report.errors.append(f"unsupported or missing schemaversion: {version or 'none'}")
        return

    resources = {}
    for res in (c for c in root.iter() if _local(c.tag) == "resource"):
        attrs = _attrs(res)
        identifier = attrs.get("identifier")
        if not identifier:
            report.errors.append("a resource has no identifier")
            continue
        resources[identifier] = (attrs, res)
    if not resources:
        report.errors.append("manifest declares no resources")
        return

    organizations = [c for c in root.iter() if _local(c.tag) == "organization"]
    if not organizations:
        report.errors.append("manifest declares no organization")
        return
    referenced = set()
    for item in (c for c in root.iter() if _local(c.tag) == "item"):
        ref = _attrs(item).get("identifierref")
        if ref:
            if ref not in resources:
                report.errors.append(f"item references unknown resource '{ref}'")
            else:
                referenced.add(ref)
    organizations_el = next((c for c in root.iter() if _local(c.tag) == "organizations"), None)
    default_org = _attrs(organizations_el).get("default") if organizations_el is not None else None
    title_el = next((c for c in organizations[0].iter() if _local(c.tag) == "title"), None)
    report.metadata["title"] = _text(title_el) or None
    if default_org and default_org not in {_attrs(o).get("identifier") for o in organizations}:
        report.warnings.append("organizations default does not match any organization")

    launch = []
    for identifier, (attrs, res) in resources.items():
        # Attribute names are lower-cased, so adlcp:scormtype (1.2) and scormType (2004) match.
        scorm_type = attrs.get("scormtype", "").lower()
        href = attrs.get("href")
        if href:
            real = _check_file(index, href, report, f"resource {identifier}")
            if scorm_type == "sco" and real:
                launch.append(real)
        for file_el in (c for c in res.iter() if _local(c.tag) == "file"):
            file_href = _attrs(file_el).get("href")
            if file_href:
                _check_file(index, file_href, report, f"resource {identifier} file")
    if not launch and not report.errors:
        report.errors.append("manifest has no SCO with a launch file")
    if not referenced and not report.errors:
        report.warnings.append("no organization item references a resource")
    report.launch_files = sorted(set(launch))


# --- cmi5 --------------------------------------------------------------------


def _validate_cmi5(archive: zipfile.ZipFile, index: _Archive, report: PackageReport) -> None:
    root = _read_xml(archive, index, "cmi5.xml", report)
    if root is None:
        return
    if _local(root.tag) != "coursestructure":
        report.errors.append("cmi5.xml root element must be <courseStructure>")
        return
    report.standard = "cmi5"
    course = next((c for c in root.iter() if _local(c.tag) == "course"), None)
    if course is None or not _attrs(course).get("id"):
        report.errors.append("cmi5.xml must declare a <course> with an id")
    else:
        report.metadata["title"] = (
            _text(next((c for c in course.iter() if _local(c.tag) == "title"), None)) or None
        )
    aus = [c for c in root.iter() if _local(c.tag) == "au"]
    if not aus:
        report.errors.append("cmi5.xml declares no assignable units (<au>)")
        return
    launch = []
    for au in aus:
        au_id = _attrs(au).get("id")
        url_el = next((c for c in au if _local(c.tag) == "url"), None)
        if not au_id:
            report.errors.append("an <au> has no id")
            continue
        if url_el is None or not _text(url_el):
            report.errors.append(f"au '{au_id}' has no <url>")
            continue
        real = _check_file(index, _text(url_el), report, f"au {au_id}")
        if real:
            launch.append(real)
    report.launch_files = sorted(set(launch))


# --- xAPI (Tin Can) ------------------------------------------------------------


def _validate_xapi(archive: zipfile.ZipFile, index: _Archive, report: PackageReport) -> None:
    root = _read_xml(archive, index, "tincan.xml", report)
    if root is None:
        return
    if _local(root.tag) != "tincan":
        report.errors.append("tincan.xml root element must be <tincan>")
        return
    report.standard = "xAPI"
    activities = [c for c in root.iter() if _local(c.tag) == "activity"]
    if not activities:
        report.errors.append("tincan.xml declares no activities")
        return
    launch = []
    for activity in activities:
        activity_id = _attrs(activity).get("id") or "(no id)"
        launch_el = next((c for c in activity if _local(c.tag) == "launch"), None)
        if launch_el is None or not _text(launch_el):
            report.errors.append(f"activity {activity_id} has no <launch>")
            continue
        real = _check_file(index, _text(launch_el), report, f"activity {activity_id}")
        if real:
            launch.append(real)
        name = next((c for c in activity if _local(c.tag) == "name"), None)
        report.metadata.setdefault("title", _text(name) or None)
    report.launch_files = sorted(set(launch))
