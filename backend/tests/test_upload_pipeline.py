"""Upload processing: package validation, malware scanning and quarantine, duplicate detection,
multipart uploads (local and S3 protocol), resume, and thumbnails."""

import hashlib
import io
import os
import socket
import struct
import threading
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.errors import NotFoundError
from app.core.security import Principal
from app.db.models import UploadSession, Version
from app.services import uploads as service
from app.services.malware import ClamAVScanner, SignatureScanner, build_scanner
from app.services.package_validation import Limits, validate
from app.services.thumbnails import make_thumbnail
from tests.conftest import build_package

NS = (
    'xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" '
    'xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"'
)
SCORM12 = (
    f"<manifest {NS}><metadata><schemaversion>1.2</schemaversion></metadata>"
    '<organizations default="o"><organization identifier="o"><title>Course</title>'
    '<item identifier="i" identifierref="r"/></organization></organizations>'
    '<resources><resource identifier="r" adlcp:scormtype="sco" href="index.html">'
    '<file href="index.html"/></resource></resources></manifest>'
)
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def make_zip(files: dict[str, bytes | str], compress: int = zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compress) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def headers_for(token_factory, sub="creator-1"):
    return {"Authorization": "Bearer " + token_factory(["Content Creator"], sub=sub)}


# --- package validation (pure) -------------------------------------------------


def test_scorm12_package_is_valid_and_reports_launch_and_title():
    report = validate("c.zip", make_zip({"imsmanifest.xml": SCORM12, "index.html": "x"}))
    assert report.valid and report.standard == "SCORM 1.2"
    assert report.launch_files == ["index.html"]
    assert report.metadata["title"] == "Course"


def test_scorm2004_schemaversion_is_recognized():
    manifest = SCORM12.replace("1.2", "2004 4th Edition")
    report = validate("c.zip", make_zip({"imsmanifest.xml": manifest, "index.html": "x"}))
    assert report.standard == "SCORM 2004"


@pytest.mark.parametrize(
    "files,fragment",
    [
        ({"imsmanifest.xml": SCORM12}, "missing file: index.html"),
        (
            {
                "imsmanifest.xml": SCORM12.replace('identifierref="r"', 'identifierref="nope"'),
                "index.html": "x",
            },
            "unknown resource",
        ),
        (
            {
                "imsmanifest.xml": SCORM12.replace("<schemaversion>1.2", "<schemaversion>9.9"),
                "index.html": "x",
            },
            "unsupported or missing schemaversion",
        ),
        ({"imsmanifest.xml": "<!DOCTYPE m [<!ENTITY e 'x'>]><m/>"}, "entity declarations"),
        ({"imsmanifest.xml": "<manifest>"}, "not valid XML"),
        ({"../escape.html": "x"}, "unsafe path"),
        ({"/abs.html": "x"}, "unsafe path"),
    ],
)
def test_scorm_failures_are_reported(files, fragment):
    report = validate("c.zip", make_zip(files))
    assert not report.valid
    assert any(fragment in error for error in report.errors), report.errors


def test_cmi5_requires_course_and_assignable_unit_with_existing_url():
    good = (
        '<courseStructure><course id="http://c"><title><langstring>C</langstring></title></course>'
        '<au id="http://a" moveOn="Passed"><url>play/index.html</url></au></courseStructure>'
    )
    report = validate("c.zip", make_zip({"cmi5.xml": good, "play/index.html": "x"}))
    assert report.valid and report.standard == "cmi5" and report.launch_files == ["play/index.html"]
    bad = good.replace("play/index.html", "gone.html")
    report = validate("c.zip", make_zip({"cmi5.xml": bad, "play/index.html": "x"}))
    assert any("missing file" in e for e in report.errors)


def test_xapi_requires_launch_for_each_activity():
    good = (
        '<tincan><activities><activity id="a1"><name>Lesson</name>'
        "<launch>lesson/index.html</launch></activity></activities></tincan>"
    )
    report = validate("c.zip", make_zip({"tincan.xml": good, "lesson/index.html": "x"}))
    assert report.valid and report.standard == "xAPI" and report.metadata["title"] == "Lesson"
    no_launch = good.replace("<launch>lesson/index.html</launch>", "")
    report = validate("c.zip", make_zip({"tincan.xml": no_launch}))
    assert any("has no <launch>" in e for e in report.errors)


def test_zip_bomb_and_entry_limits():
    bomb = make_zip({"big.txt": b"\0" * (4 * 1024 * 1024)}, compress=zipfile.ZIP_DEFLATED)
    report = validate("c.zip", bomb, Limits(max_compression_ratio=100))
    assert any("compression ratio" in e for e in report.errors)
    many = make_zip({f"f{i}.txt": "x" for i in range(5)})
    assert any(
        "more than 3 entries" in e for e in validate("c.zip", many, Limits(max_entries=3)).errors
    )


def test_generic_zip_warns_or_fails_by_policy():
    plain = make_zip({"index.html": "x"})
    report = validate("c.zip", plain)
    assert report.valid and report.warnings
    strict = validate("c.zip", plain, Limits(allow_generic_zip=False))
    assert not strict.valid


def test_pdf_header_eof_and_metadata():
    good = b"%PDF-1.4\n1 0 obj << /Title (Notes) /Type /Page >> endobj\n%%EOF\n"
    report = validate("notes.pdf", good)
    assert (
        report.valid and report.metadata["title"] == "Notes" and report.metadata["page_count"] == 1
    )
    assert not validate("notes.pdf", b"%PDF-1.4 truncated").valid
    assert not validate("notes.pdf", b"not a pdf").valid


# --- malware scanning ----------------------------------------------------------------


def test_signature_scanner_detects_eicar_executables_and_nested_bombs():
    scanner = SignatureScanner()
    assert scanner.scan(EICAR).status == "infected"
    assert scanner.scan(make_zip({"index.html": EICAR.decode()})).status == "infected"
    exe = scanner.scan(make_zip({"tools/setup.exe": b"MZ\x90\x00"}))
    assert exe.status == "infected" and "setup.exe" in exe.detail
    magic = scanner.scan(make_zip({"helper.bin": b"\x7fELF...."}))
    assert magic.status == "infected"
    deep = make_zip({"a.zip": make_zip({"b.zip": make_zip({"c.zip": make_zip({"x.html": "y"})})})})
    assert scanner.scan(deep).status == "infected"
    assert scanner.scan(make_zip({"index.html": "fine"})).clean


def _fake_clamd(reply: bytes):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.recv(10)  # zINSTREAM\0
            while True:
                (length,) = struct.unpack(">I", conn.recv(4))
                if length == 0:
                    break
                remaining = length
                while remaining:
                    remaining -= len(conn.recv(min(remaining, 65536)))
            conn.sendall(reply)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server, server.getsockname()[1], thread


def test_clamav_protocol_reports_clean_found_and_errors():
    server, port, thread = _fake_clamd(b"stream: OK\0")
    assert ClamAVScanner("127.0.0.1", port).scan(b"hello").clean
    thread.join(2)
    server.close()

    server, port, thread = _fake_clamd(b"stream: Eicar-Test-Signature FOUND\0")
    result = ClamAVScanner("127.0.0.1", port).scan(b"hello")
    assert result.status == "infected" and "Eicar" in result.detail
    thread.join(2)
    server.close()

    unreachable = ClamAVScanner("127.0.0.1", 1, timeout=1).scan(b"x")
    assert unreachable.status == "error"


def test_build_scanner_requires_host_when_clamav_selected(settings):
    settings.malware_scanner = "clamav"
    settings.clamav_host = ""
    with pytest.raises(RuntimeError):
        build_scanner(settings)


def test_infected_upload_is_quarantined_and_never_served(client, token_factory):
    headers = headers_for(token_factory)
    response = client.post(
        "/api/v1/content",
        data={"title": "Bad course"},
        files={"file": ("course.zip", make_zip({"tools/run.exe": b"MZ\x90"}), "application/zip")},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "quarantined"
    assert client.get(f"/api/v1/content/{body['id']}/download", headers=headers).status_code == 403
    assert (
        client.get(f"/api/v1/content/{body['id']}/package/files", headers=headers).status_code
        == 403
    )
    detail = client.get(f"/api/v1/content/{body['id']}", headers=headers).json()
    assert detail["versions"] and detail["metadata"] is not None


def test_scanner_error_fails_closed_to_quarantine(client, token_factory, settings):
    server, port, thread = _fake_clamd(b"INSTREAM size limit exceeded ERROR\0")
    settings.malware_scanner = "clamav"
    settings.clamav_host = "127.0.0.1"
    settings.clamav_port = port
    try:
        response = client.post(
            "/api/v1/content",
            data={"title": "Unscanned"},
            files={"file": ("course.zip", build_package(), "application/zip")},
            headers=headers_for(token_factory),
        )
    finally:
        thread.join(2)
        server.close()
    assert response.status_code == 201 and response.json()["status"] == "quarantined"


def test_invalid_package_is_rejected_and_nothing_is_stored(client, token_factory, db_session):
    response = client.post(
        "/api/v1/content",
        data={"title": "Broken"},
        files={
            "file": (
                "course.zip",
                make_zip({"imsmanifest.xml": "<manifest/>", "x.html": "y"}),
                "application/zip",
            )
        },
        headers=headers_for(token_factory),
    )
    assert response.status_code == 400
    assert "package validation failed" in response.json()["message"]
    assert db_session.query(Version).count() == 0


def test_duplicate_detection_and_explicit_copy(client, token_factory):
    headers = headers_for(token_factory)
    package = build_package()
    first = client.post(
        "/api/v1/content",
        data={"title": "One"},
        files={"file": ("c.zip", package, "application/zip")},
        headers=headers,
    )
    assert first.status_code == 201
    again = client.post(
        "/api/v1/content",
        data={"title": "Two"},
        files={"file": ("c.zip", package, "application/zip")},
        headers=headers,
    )
    assert again.status_code == 409 and again.json()["error"] == "duplicate"
    assert first.json()["id"] in again.json()["message"]


def test_thumbnail_is_escaped_svg_without_pillow(client, token_factory):
    headers = headers_for(token_factory)
    created = client.post(
        "/api/v1/content",
        data={"title": "<script>alert(1)</script>"},
        files={"file": ("c.zip", build_package(), "application/zip")},
        headers=headers,
    ).json()
    thumb = client.get(f"/api/v1/content/{created['id']}/thumbnail", headers=headers)
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith(("image/svg+xml", "image/png"))
    assert b"<script>" not in thumb.content
    data, media = make_thumbnail(b"not a zip", "t <b>", "PDF")
    assert media == "image/svg+xml" and b"<b>" not in data


# --- multipart uploads (local protocol) ----------------------------------------------


def _big_package(size: int = 2_500_000) -> bytes:
    return make_zip(
        {"imsmanifest.xml": SCORM12, "index.html": "x", "media/big.bin": os.urandom(size)}
    )


def test_multipart_resume_retry_and_complete(client, token_factory):
    headers = headers_for(token_factory)
    package = _big_package()
    created = client.post(
        "/api/v1/uploads",
        json={
            "title": "Big course",
            "filename": "big.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
            "part_size": 1024 * 1024,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    upload = created.json()
    assert upload["part_count"] == 3 and upload["missing_parts"] == [1, 2, 3]
    base = f"/api/v1/uploads/{upload['id']}"
    size = upload["part_size"]
    chunks = [package[i * size : (i + 1) * size] for i in range(3)]

    # Parts can arrive out of order. The second part goes first, as if the first attempt failed.
    target = client.get(f"{base}/parts/2/url", headers=headers).json()
    assert target["method"] == "PUT" and target["direct"] is False
    assert client.put(target["url"], content=chunks[1], headers=headers).status_code == 200

    status = client.get(base, headers=headers).json()
    assert status["completed_parts"] == [2] and status["missing_parts"] == [1, 3]

    early = client.post(f"{base}/complete", json={}, headers=headers)
    assert early.status_code == 409 and "missing parts" in early.json()["message"]

    # A wrong checksum is refused and nothing is stored for that part.
    bad = client.put(
        f"{base}/parts/1", content=chunks[0], headers={**headers, "X-Part-Sha256": "0" * 64}
    )
    assert bad.status_code == 400

    # Wrong size is refused.
    short = client.put(f"{base}/parts/1", content=chunks[0][:10], headers=headers)
    assert short.status_code == 400

    assert client.put(f"{base}/parts/1", content=chunks[0], headers=headers).status_code == 200
    # Retrying a part replaces it. Completed work is never duplicated.
    assert client.put(f"{base}/parts/1", content=chunks[0], headers=headers).status_code == 200
    assert client.put(f"{base}/parts/3", content=chunks[2], headers=headers).status_code == 200

    done = client.post(f"{base}/complete", json={}, headers=headers)
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["status"] == "draft" and result["scan_status"] == "clean"
    assert result["validation"]["standard"] == "SCORM 1.2"
    assert result["thumbnail_url"].endswith("/thumbnail")
    assert client.post(f"{base}/complete", json={}, headers=headers).status_code == 409
    assert (
        client.get(f"/api/v1/content/{result['id']}/download", headers=headers).content == package
    )


def test_multipart_duplicate_then_explicit_copy_and_abort(client, token_factory):
    headers = headers_for(token_factory)
    package = build_package()
    original = client.post(
        "/api/v1/content",
        data={"title": "Original"},
        files={"file": ("c.zip", package, "application/zip")},
        headers=headers,
    )
    assert original.status_code == 201
    upload = client.post(
        "/api/v1/uploads",
        json={
            "title": "Copy",
            "filename": "c.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
        },
        headers=headers,
    ).json()
    base = f"/api/v1/uploads/{upload['id']}"
    client.put(f"{base}/parts/1", content=package, headers=headers)
    dup = client.post(f"{base}/complete", json={}, headers=headers)
    assert dup.status_code == 409 and dup.json()["error"] == "duplicate"
    # The session stays assembled, so the user can choose to keep a second copy.
    ok = client.post(f"{base}/complete", json={"allow_duplicate": True}, headers=headers)
    assert ok.status_code == 200

    second = client.post(
        "/api/v1/uploads",
        json={
            "title": "Abandoned",
            "filename": "d.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
        },
        headers=headers,
    ).json()
    aborted = client.post(f"/api/v1/uploads/{second['id']}/abort", headers=headers)
    assert aborted.json()["status"] == "aborted"
    late = client.put(f"/api/v1/uploads/{second['id']}/parts/1", content=package, headers=headers)
    assert late.status_code == 409


def test_invalid_multipart_package_is_rejected(client, token_factory):
    headers = headers_for(token_factory)
    package = make_zip({"imsmanifest.xml": "<manifest/>", "x.html": "y"})
    upload = client.post(
        "/api/v1/uploads",
        json={
            "title": "Bad",
            "filename": "bad.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
        },
        headers=headers,
    ).json()
    base = f"/api/v1/uploads/{upload['id']}"
    client.put(f"{base}/parts/1", content=package, headers=headers)
    response = client.post(f"{base}/complete", json={}, headers=headers)
    assert response.status_code == 400
    assert client.get(base, headers=headers).json()["status"] == "rejected"


def test_uploads_belong_to_their_owner(client, token_factory):
    package = build_package()
    upload = client.post(
        "/api/v1/uploads",
        json={
            "title": "Mine",
            "filename": "c.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
        },
        headers=headers_for(token_factory, sub="creator-1"),
    ).json()
    other = headers_for(token_factory, sub="creator-2")
    assert client.get(f"/api/v1/uploads/{upload['id']}", headers=other).status_code == 404


def test_expired_sessions_are_refused(client, token_factory, db_session):
    headers = headers_for(token_factory)
    package = build_package()
    upload = client.post(
        "/api/v1/uploads",
        json={
            "title": "Late",
            "filename": "c.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
        },
        headers=headers,
    ).json()
    row = db_session.get(UploadSession, upload["id"])
    from datetime import UTC, datetime, timedelta

    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    response = client.put(
        f"/api/v1/uploads/{upload['id']}/parts/1", content=package, headers=headers
    )
    assert response.status_code == 400 and "expired" in response.json()["message"]


# --- S3 presigned multipart protocol (in-memory fake; no AWS calls) ------------------------


class FakeS3:
    """Mimics the parts of the S3 client the service uses. Parts are PUT via presigned URLs."""

    def __init__(self, objects: dict) -> None:
        self.objects = objects
        self.uploads: dict[str, dict] = {}
        self.counter = 0

    def create_multipart_upload(self, *, Bucket, Key, **kwargs):
        self.counter += 1
        upload_id = f"up-{self.counter}"
        self.uploads[upload_id] = {"key": Key, "parts": {}}
        return {"UploadId": upload_id}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        assert operation == "upload_part"
        return (
            f"https://s3.fake/{Params['Bucket']}/{Params['Key']}"
            f"?uploadId={Params['UploadId']}&partNumber={Params['PartNumber']}&X-Expires={ExpiresIn}"
        )

    def direct_put(self, url: str, body: bytes) -> str:
        query = parse_qs(urlparse(url).query)
        upload = self.uploads[query["uploadId"][0]]
        number = int(query["partNumber"][0])
        etag = f'"{hashlib.md5(body).hexdigest()}"'
        upload["parts"][number] = (body, etag)
        return etag

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        upload = self.uploads.pop(UploadId)
        assert upload["key"] == Key
        ordered = []
        for part in MultipartUpload["Parts"]:
            body, etag = upload["parts"][part["PartNumber"]]
            assert etag == part["ETag"], "ETag mismatch"
            ordered.append(body)
        self.objects[Key] = b"".join(ordered)
        return {"Key": Key}

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.uploads.pop(UploadId, None)


class FakeS3Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.client = FakeS3(self.objects)
        self.bucket = "test-bucket"

    def save(self, key, data):
        self.objects[key] = data

    def open(self, key):
        if key not in self.objects:
            raise FileNotFoundError(key)
        return io.BytesIO(self.objects[key])

    def delete(self, key):
        self.objects.pop(key, None)


def test_s3_presigned_multipart_flow(settings, db_session):
    settings.storage_backend = "s3"
    storage = FakeS3Storage()
    actor = Principal(subject="creator-1", roles=frozenset({"Content Creator"}))
    package = _big_package(size=6 * 1024 * 1024)
    row = service.create_session(
        db_session,
        storage,
        settings,
        actor,
        title="S3 course",
        filename="s3.zip",
        content_type="application/zip",
        size_bytes=len(package),
        part_size=5 * 1024 * 1024,
    )
    assert row.part_count == 2 and row.part_size >= 5 * 1024 * 1024
    for number in (1, 2):
        target = service.part_target(db_session, storage, settings, actor, row.id, number)
        assert target["direct"] is True and target["url"].startswith("https://s3.fake/")
        start = (number - 1) * row.part_size
        body = package[start : start + (row.part_size if number == 1 else len(package) - start)]
        etag = storage.client.direct_put(target["url"], body)
        service.record_direct_part(
            db_session, settings, actor, row.id, number, len(body), etag, None
        )
    lo = service.complete(db_session, storage, settings, actor, row.id, allow_duplicate=False)
    assert lo.versions[-1].size_bytes == len(package)
    assert lo.versions[-1].sha256 == hashlib.sha256(package).hexdigest()
    assert storage.client.uploads == {}  # the multipart upload was completed, not left dangling
    assert not any(
        key.startswith("_uploads/") and key.endswith("/object") for key in storage.objects
    )


def test_s3_part_with_wrong_etag_fails_completion(settings, db_session):
    settings.storage_backend = "s3"
    storage = FakeS3Storage()
    actor = Principal(subject="creator-1", roles=frozenset({"Content Creator"}))
    package = build_package()
    row = service.create_session(
        db_session,
        storage,
        settings,
        actor,
        title="One",
        filename="c.zip",
        content_type="application/zip",
        size_bytes=len(package),
        part_size=None,
    )
    target = service.part_target(db_session, storage, settings, actor, row.id, 1)
    storage.client.direct_put(target["url"], package)
    service.record_direct_part(
        db_session, settings, actor, row.id, 1, len(package), '"wrong"', None
    )
    with pytest.raises(AssertionError):
        service.complete(db_session, storage, settings, actor, row.id, allow_duplicate=False)


def test_unknown_session_is_not_found(settings, db_session):
    actor = Principal(subject="creator-1", roles=frozenset({"Content Creator"}))
    with pytest.raises(NotFoundError):
        service.abort(db_session, FakeS3Storage(), settings, actor, "missing")


def test_multipart_infected_package_is_quarantined(client, token_factory):
    headers = headers_for(token_factory)
    infected = make_zip({"tools/run.exe": b"MZ\x90\x00 payload"})
    upload = client.post(
        "/api/v1/uploads",
        json={
            "title": "Infected",
            "filename": "bad.zip",
            "content_type": "application/zip",
            "size_bytes": len(infected),
        },
        headers=headers,
    ).json()
    base = f"/api/v1/uploads/{upload['id']}"
    assert client.put(f"{base}/parts/1", content=infected, headers=headers).status_code == 200
    done = client.post(f"{base}/complete", json={}, headers=headers)
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["quarantined"] is True and result["status"] == "quarantined"
    assert (
        client.get(f"/api/v1/content/{result['id']}/download", headers=headers).status_code == 403
    )


def test_unreadable_upload_fails_closed_and_stores_nothing(
    client, token_factory, monkeypatch, db_session
):
    from app.storage.local import LocalStorage

    original_open = LocalStorage.open

    def blocked(self, key):
        if "/parts/" in key:
            raise OSError(22, "blocked by host security software")
        return original_open(self, key)

    monkeypatch.setattr(LocalStorage, "open", blocked)
    headers = headers_for(token_factory)
    package = build_package()
    base_upload = client.post(
        "/api/v1/uploads",
        json={
            "title": "Blocked",
            "filename": "c.zip",
            "content_type": "application/zip",
            "size_bytes": len(package),
        },
        headers=headers,
    ).json()
    base = f"/api/v1/uploads/{base_upload['id']}"
    client.put(f"{base}/parts/1", content=package, headers=headers)
    response = client.post(f"{base}/complete", json={}, headers=headers)
    assert response.status_code == 503
    assert response.json()["error"] == "storage_unavailable"
    assert client.get(base, headers=headers).json()["status"] == "rejected"
    assert db_session.query(Version).count() == 0
