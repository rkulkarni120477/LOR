"""Content interoperability: portable bundles and standards exports.

A bundle is a zip with:
  manifest.json       format name and version, source id, file hash
  metadata.json       the LOM record, kind, status
  dublin-core.xml     Dublin Core rendering of the LOM fields (via the crosswalk)
  xapi-activity.json  an xAPI activity definition for the item
  package/<file>      the latest package bytes, for file items

Import accepts bundles that contain a package and creates a new item through the normal pipeline
(scan, validation, duplicate check). Bundles without a package are refused for now: rich text and
quizzes travel as metadata plus their body, which is not yet importable.
"""

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import LearningObject
from app.services import content as content_service
from app.services import taxonomy
from app.storage.base import StorageBackend

FORMAT = "elor-bundle"
VERSION = 1
DC_NS = "http://purl.org/dc/elements/1.1/"
DCT_NS = "http://purl.org/dc/terms/"
MAX_MEMBERS = 50
MAX_BUNDLE_BYTES = 300 * 1024 * 1024


def _dublin_core(lom: dict) -> str:
    mapped = taxonomy.crosswalk(lom, "dublin-core")["mapped"]
    parts = []
    for target, value in mapped.items():
        prefix, name = target.split(":", 1)
        ns_attr = "dc" if prefix == "dc" else "dcterms"
        for item in value if isinstance(value, list) else [value]:
            parts.append(f"  <{ns_attr}:{name}>{escape(str(item))}</{ns_attr}:{name}>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<metadata xmlns:dc="{DC_NS}" xmlns:dcterms="{DCT_NS}">\n'
        + "\n".join(parts)
        + "\n</metadata>\n"
    )


def _xapi_activity(lo: LearningObject, lom: dict) -> dict:
    activity = {
        "id": f"urn:elor:learning-object:{lo.id}",
        "definition": {
            "name": {"en-US": lo.title},
            "type": "http://adlnet.gov/expapi/activities/course",
        },
    }
    if lom.get("description"):
        activity["definition"]["description"] = {"en-US": lom["description"]}
    return activity


def export_bundle(
    session: Session, storage: StorageBackend, lo: LearningObject
) -> tuple[bytes, str]:
    meta = lo.metadata_record
    lom = taxonomy.current_lom(meta) if meta is not None else {"title": lo.title, "custom": {}}
    latest = max(lo.versions, key=lambda v: v.version_number, default=None)
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "source_id": lo.id,
        "kind": lo.kind,
        "exported_at": datetime.now(UTC).isoformat(),
        "package": None,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if latest is not None and lo.kind == "file":
            with storage.open(latest.storage_key) as stream:
                data = stream.read()
            name = latest.original_filename
            manifest["package"] = {
                "file": name,
                "content_type": latest.content_type,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
            archive.writestr(f"package/{name}", data)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        archive.writestr(
            "metadata.json",
            json.dumps(
                {"kind": lo.kind, "status": lo.status, "lom": lom},
                indent=2,
                sort_keys=True,
                default=str,
            ),
        )
        archive.writestr("dublin-core.xml", _dublin_core(lom))
        archive.writestr("xapi-activity.json", json.dumps(_xapi_activity(lo, lom), indent=2))
    return buffer.getvalue(), f"elor-{lo.id}.zip"


def import_bundle(
    session: Session, storage: StorageBackend, settings: Settings, actor: Principal, data: bytes
) -> LearningObject:
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValidationFailure("the bundle is too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationFailure("the file is not a zip bundle") from exc
    with archive:
        names = archive.namelist()
        if len(names) > MAX_MEMBERS:
            raise ValidationFailure("the bundle has too many files")
        for name in names:
            if (
                name.startswith(("/", "\\"))
                or ".." in name.replace("\\", "/").split("/")
                or ":" in name
            ):
                raise ValidationFailure(f"unsafe path in bundle: {name!r}")
        try:
            manifest = json.loads(archive.read("manifest.json"))
            metadata = json.loads(archive.read("metadata.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValidationFailure("the bundle has no valid manifest or metadata") from exc
        if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValidationFailure("unsupported bundle format or version")
        package = manifest.get("package")
        if not package:
            raise ValidationFailure(
                "this bundle has no package; only bundles with a package can be imported"
            )
        member = f"package/{package['file']}"
        if member not in names:
            raise ValidationFailure("the package named in the manifest is missing from the bundle")
        payload = archive.read(member)
    if hashlib.sha256(payload).hexdigest() != package.get("sha256"):
        raise ValidationFailure("the package does not match the hash in the manifest")
    lom = dict(metadata.get("lom") or {})
    title = (lom.get("title") or package["file"]).strip()[:500]
    lo = content_service.ingest(
        session,
        storage,
        title=title,
        filename=package["file"],
        content_type=package.get("content_type", "application/zip"),
        data=payload,
        max_bytes=settings.max_upload_bytes,
        actor=actor,
        settings=settings,
    )
    return lo


def xapi_activity(session: Session, lo_id: str) -> dict:
    lo = session.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    meta = lo.metadata_record
    lom = taxonomy.current_lom(meta) if meta is not None else {"title": lo.title}
    return _xapi_activity(lo, lom)
