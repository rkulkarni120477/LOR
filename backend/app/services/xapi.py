"""Store xAPI statements. Actor resolution maps mailto: identifiers to local users when known."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.models import User, XapiStatement
from app.schemas.xapi import XapiStatement as XapiStatementIn


def _resolve_actor_id(session: Session, actor_key: str) -> int | None:
    if not actor_key.startswith("mailto:"):
        return None
    email = actor_key.removeprefix("mailto:")
    return session.scalar(select(User.id).where(User.email == email))


def store_statements(session: Session, statements: list[XapiStatementIn]) -> list[str]:
    ids: list[str] = []
    for stmt in statements:
        stmt_id = stmt.id or str(uuid.uuid4())
        if session.get(XapiStatement, stmt_id) is not None:
            raise ConflictError(f"statement {stmt_id} already exists")
        actor_key = stmt.actor.key
        session.add(
            XapiStatement(
                id=stmt_id,
                actor_key=actor_key,
                actor_id=_resolve_actor_id(session, actor_key),
                verb_id=stmt.verb.id,
                object_id=stmt.object.id,
                result=stmt.result,
                statement=stmt.model_dump(mode="json", exclude_none=True) | {"id": stmt_id},
                stored_at=datetime.now(UTC),
            )
        )
        ids.append(stmt_id)
    session.commit()
    return ids
