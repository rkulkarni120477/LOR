import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.security import Principal, get_principal
from app.db.session import get_db
from app.services import player
from app.storage.base import StorageBackend

router = APIRouter(prefix="/library", tags=["format previews"])


@router.post("/{lo_id}/preview-session")
def create_session(
    lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
):
    return player.issue(db, lo_id, actor)


@router.post("/{lo_id}/preview-files/{token}/__runtime")
async def runtime(lo_id: str, token: str, request: Request, db: Session = Depends(get_db)):
    ticket, _ = player.resolve(db, lo_id, token)
    data = await request.body()
    if len(data) > 64000:
        raise HTTPException(413, "Runtime data exceeds the limit")
    try:
        result = player.save_activity(db, ticket, json.loads(data))
    except ValueError as exc:
        raise HTTPException(422, "Invalid runtime JSON") from exc
    return Response(json.dumps(result), media_type="application/json", headers=player.headers())


@router.get("/{lo_id}/preview-files/{token}/{path:path}")
def asset(
    lo_id: str,
    token: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
):
    ticket, version = player.resolve(db, lo_id, token)
    if path in {"__fetch", "__lrs/statements", "__lrs/activities/state"}:
        row = player.activity(db, ticket)
        values = row.data if row else {}
        if path == "__fetch":
            result = {"auth-token": "Bearer " + token}
        elif path == "__lrs/statements":
            statements = (values or {}).get("xapi.statements", [])
            statement_id = request.query_params.get("statementId")
            result = (
                next((s for s in statements if s.get("id") == statement_id), None)
                if statement_id
                else {"statements": statements, "more": ""}
            )
            if result is None:
                raise HTTPException(404, "Statement not found")
        else:
            key = "xapi.state." + request.query_params.get("stateId", "state")[:100]
            result = (values or {}).get(key, {})
        return Response(json.dumps(result), media_type="application/json", headers=player.headers())
    base = f"/api/v1/library/{lo_id}/preview-files/{token}/"
    data, mime = player.serve(db, storage, ticket, version, path, base)
    response_headers = player.headers()
    response_headers["Accept-Ranges"] = "bytes"
    requested_range = request.headers.get("range")
    if requested_range:
        import re

        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested_range)
        if match is None or not data or not any(match.groups()):
            return Response(
                status_code=416,
                headers={**response_headers, "Content-Range": f"bytes */{len(data)}"},
            )
        first, last = match.groups()
        start = int(first) if first else max(0, len(data) - int(last))
        end = min(int(last), len(data) - 1) if last and first else len(data) - 1
        if start > end or start >= len(data):
            return Response(
                status_code=416,
                headers={**response_headers, "Content-Range": f"bytes */{len(data)}"},
            )
        response_headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(
            data[start : end + 1], status_code=206, media_type=mime, headers=response_headers
        )
    return Response(data, media_type=mime, headers=response_headers)


@router.post("/{lo_id}/preview-files/{token}/__lrs/statements")
async def statements(lo_id: str, token: str, request: Request, db: Session = Depends(get_db)):
    import uuid

    ticket, _ = player.resolve(db, lo_id, token)
    data = await request.body()
    if len(data) > 64000:
        raise HTTPException(413, "Statement payload too large")
    try:
        values = json.loads(data)
    except ValueError as exc:
        raise HTTPException(422, "Invalid xAPI JSON") from exc
    values = values if isinstance(values, list) else [values]
    if len(values) > 100 or not all(
        isinstance(v, dict)
        and isinstance(v.get("verb"), dict)
        and isinstance(v.get("object"), dict)
        for v in values
    ):
        raise HTTPException(422, "Invalid xAPI statements")
    row = player.activity(db, ticket)
    previous = (row.data or {}).get("xapi.statements", []) if row else []
    values = [{**v, "id": v.get("id") or str(uuid.uuid4())} for v in values]
    ids = [v["id"] for v in values]
    if any(not isinstance(identity, str) or len(identity) > 64 for identity in ids):
        raise HTTPException(422, "Invalid statement ID")
    combined = {v["id"]: v for v in previous}
    for value in values:
        if value["id"] in combined and combined[value["id"]] != value:
            raise HTTPException(409, "A statement ID cannot be reused with different content")
        combined[value["id"]] = value
    player.save_activity(db, ticket, {"xapi.statements": list(combined.values())[-100:]})
    return Response(
        json.dumps(ids),
        media_type="application/json",
        headers=player.headers(),
    )


@router.put("/{lo_id}/preview-files/{token}/__lrs/activities/state")
async def put_state(lo_id: str, token: str, request: Request, db: Session = Depends(get_db)):
    ticket, _ = player.resolve(db, lo_id, token)
    payload = await request.body()
    if len(payload) > 64000:
        raise HTTPException(413, "State exceeds the preview limit")
    try:
        value = json.loads(payload)
    except ValueError:
        value = payload.decode("utf-8", "replace")
    key = "xapi.state." + request.query_params.get("stateId", "state")[:100]
    player.save_activity(db, ticket, {key: value})
    return Response(status_code=204, headers=player.headers())


@router.options("/{lo_id}/preview-files/{token}/{path:path}")
def preflight(lo_id: str, token: str, path: str, db: Session = Depends(get_db)):
    player.resolve(db, lo_id, token)
    return Response(
        status_code=204,
        headers={
            **player.headers(),
            "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Experience-API-Version, If-Match, If-None-Match, Range",
            "Access-Control-Max-Age": "300",
        },
    )
