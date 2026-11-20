from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def record(
    session: Session,
    *,
    actor_subject: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the current transaction. The caller commits.
    Every audit row is also queued for webhooks subscribed to its action."""
    session.add(
        AuditLog(
            actor_subject=actor_subject,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
    from app.services import integrations  # local import: integrations depends on the models only

    integrations.enqueue(session, action, entity_type, entity_id, actor_subject, details)
