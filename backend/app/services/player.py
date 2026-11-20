"""Scoped, expiring package delivery. Active content always runs in an opaque-origin sandbox."""

import hashlib
import html
import io
import json
import mimetypes
import posixpath
import re
import secrets
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import effective_principal
from app.db.models import LearningObject, PackageActivity, PreviewTicket, Version
from app.services.access import require_object
from app.services.content import assert_servable
from app.services.formats import office_preview


def issue(session, lo_id, actor):
    require_object(session, lo_id, actor, "read")
    lo = session.get(LearningObject, lo_id)
    version = max(lo.versions, key=lambda v: v.version_number, default=None)
    if version is None:
        raise HTTPException(404, "No file is attached")
    assert_servable(version)
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session.execute(delete(PreviewTicket).where(PreviewTicket.expires_at <= now))
    expires = now + timedelta(minutes=15)
    if actor.expires_at:
        expires = min(expires, actor.expires_at.replace(tzinfo=UTC))
    session.add(
        PreviewTicket(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            lo_id=lo_id,
            version_id=version.id,
            subject=actor.subject,
            roles=list(actor.roles if actor.source_roles is None else actor.source_roles),
            expires_at=expires,
        )
    )
    session.commit()
    base = f"/api/v1/library/{lo_id}/preview-files/{token}/"
    ext = PurePosixPath(version.original_filename).suffix.lower()
    mode = (
        "package"
        if ext in {".zip", ".h5p", ".html", ".htm"}
        else "document"
        if ext in {".docx", ".pptx"}
        else "pdf"
        if ext == ".pdf"
        else "video"
        if ext == ".mp4"
        else "audio"
        if ext == ".mp3"
        else "image"
    )
    url = base + ("__launch" if mode in {"package", "document"} else "__file")
    if mode == "package":
        import uuid
        from urllib.parse import urlencode

        origin = get_settings().app_origin.rstrip("/")
        actor_id = hashlib.sha256(actor.subject.encode()).hexdigest()[:24]
        url += "?" + urlencode(
            {
                "endpoint": origin + base + "__lrs/",
                "fetch": origin + base + "__fetch",
                "actor": json.dumps(
                    {"objectType": "Agent", "account": {"homePage": origin, "name": actor_id}}
                ),
                "registration": str(uuid.uuid4()),
                "activityId": origin + "/objects?id=" + lo_id,
                "activity_id": origin + "/objects?id=" + lo_id,
                "auth": "Bearer " + token,
            }
        )
    return {"url": url, "mode": mode, "expires_at": expires, "filename": version.original_filename}


def resolve(session, lo_id, token):
    ticket = session.get(PreviewTicket, hashlib.sha256(token.encode()).hexdigest())
    if (
        ticket is None
        or ticket.lo_id != lo_id
        or ticket.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
    ):
        raise HTTPException(401, "Preview expired; reopen it")
    actor = effective_principal(session, ticket.subject, None, frozenset(ticket.roles))
    require_object(session, lo_id, actor, "read")
    version = session.get(Version, ticket.version_id)
    assert_servable(version)
    return ticket, version


def activity(session, ticket):
    return session.scalar(
        select(PackageActivity).where(
            PackageActivity.lo_id == ticket.lo_id,
            PackageActivity.version_id == ticket.version_id,
            PackageActivity.subject == ticket.subject,
        )
    )


def save_activity(session, ticket, values):
    actor = effective_principal(session, ticket.subject, None, frozenset(ticket.roles))
    if not actor.can("activity.write"):
        raise HTTPException(403, "This role cannot persist learning activity")
    if not isinstance(values, dict) or len(json.dumps(values)) > 64000:
        raise HTTPException(422, "Runtime state must be an object smaller than 64 KB")
    if any(not isinstance(k, str) or not k.startswith(("cmi.", "xapi.", "h5p.")) for k in values):
        raise HTTPException(422, "Unsupported runtime key")
    row = activity(session, ticket)
    if row is None:
        row = PackageActivity(
            lo_id=ticket.lo_id, version_id=ticket.version_id, subject=ticket.subject, data={}
        )
        session.add(row)
    row.data = {**(row.data or {}), **values}
    if len(json.dumps(row.data)) > 64000:
        raise HTTPException(422, "Accumulated runtime state exceeds 64 KB")
    session.commit()
    return {"saved": True}


def headers():
    origin = get_settings().app_origin.rstrip("/")
    # No same-origin sandbox permission, popups, forms, top navigation or external networking.
    policy = (
        "sandbox allow-scripts; default-src 'none'; "
        f"script-src 'unsafe-inline' 'unsafe-eval' {origin}; "
        f"style-src 'unsafe-inline' {origin}; img-src data: blob: {origin}; "
        f"media-src blob: {origin}; font-src data: {origin}; connect-src {origin}; "
        f"frame-src {origin} blob:; worker-src blob: {origin}; "
        f"base-uri {origin}; form-action 'none'"
    )
    return {
        "Content-Security-Policy": policy,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Access-Control-Allow-Origin": "*",
    }


def bootstrap(session, ticket, base):
    row = activity(session, ticket)
    state = row.data if row else {}
    learner = hashlib.sha256(ticket.subject.encode()).hexdigest()[:24]
    config = json.dumps({"state": state, "url": base + "__runtime", "id": learner}).replace(
        "<", "\\u003c"
    )
    from pathlib import Path

    code = Path(__file__).resolve().parents[1] / "assets" / "player.js"
    return (
        "<script>"
        + Path(str(code)).read_text(encoding="utf-8").replace("__ELOR_CONFIG__", config)
        + "</script>"
    )


def serve(session, storage, ticket, version, path, base):
    # Never extract packages to disk; reject traversal even in URL-encoded inputs.
    if "\\" in path or "\x00" in path or any(p == ".." for p in PurePosixPath(path).parts):
        raise HTTPException(404, "Invalid package path")
    with storage.open(version.storage_key) as stream:
        data = stream.read()
    ext = PurePosixPath(version.original_filename).suffix.lower()
    if path == "__file":
        return data, version.content_type
    origin = get_settings().app_origin.rstrip("/")
    absolute_base = origin + base
    if ext in {".docx", ".pptx"}:
        return (
            "<!doctype html><meta charset='utf-8'><style>body{font:16px Arial;padding:24px}"
            "section{border-bottom:1px solid #ddd;padding:20px}</style>"
            + office_preview(version.original_filename, data)
        ).encode(), "text/html"
    if ext in {".html", ".htm"}:
        payload = data
        path = "index.html"
    elif ext in {".zip", ".h5p"}:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if path == "__launch":
                if ext == ".h5p":
                    runtime = origin + "/h5p-runtime/"
                    row = activity(session, ticket)
                    options = json.dumps(
                        {
                            "base": absolute_base,
                            "runtime": runtime,
                            "state": (row.data or {}).get("h5p.state") if row else None,
                        }
                    ).replace("<", "\\u003c")
                    from pathlib import Path

                    code = (Path(__file__).resolve().parents[1] / "assets" / "h5p.js").read_text(
                        encoding="utf-8"
                    )
                    page = (
                        '<!doctype html><meta charset="utf-8"><div id="h5p"></div>'
                        + f'<script src="{runtime}main.bundle.js"></script><script>'
                        + code.replace("__ELOR_CONFIG__", options)
                        + "</script>"
                    )
                    return page.encode(), "text/html"
                candidates = (version.validation or {}).get("launch_files", [])
                path = next((p for p in candidates if p in archive.namelist()), None) or next(
                    (
                        p
                        for p in archive.namelist()
                        if p.lower().endswith(("index.html", "index.htm"))
                    ),
                    None,
                )
                if not path:
                    raise HTTPException(422, "No local HTML launch page exists in this package")
            try:
                info = archive.getinfo(path)
            except KeyError as exc:
                raise HTTPException(404, "Package resource not found") from exc
            if info.file_size > 200 * 1024 * 1024:
                raise HTTPException(413, "Package resource exceeds the preview size limit")
            payload = archive.read(info)
    else:
        raise HTTPException(404, "Not a package")
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if path.endswith((".html", ".htm")):
        text = payload.decode("utf-8", "replace")
        text = re.sub(r"<base\b[^>]*>", "", text, flags=re.I)
        folder = posixpath.dirname(path)
        prefix = (
            "<!doctype html><meta charset='utf-8'><base href='"
            + html.escape(absolute_base + (quote(folder) + "/" if folder else ""), quote=True)
            + "'>"
            + bootstrap(session, ticket, absolute_base)
        )
        # Root-relative package resources stay inside the scoped capability path.
        text = re.sub(
            r"""((?:src|href)\s*=\s*["'])/(?!/)""", lambda m: m[1] + absolute_base, text, flags=re.I
        )
        return (prefix + text).encode(), "text/html"
    return payload, mime
