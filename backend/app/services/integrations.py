"""Outbound webhooks and branding.

Events are the audit actions the system already records (workflow.published, content.create,
...). audit.record() queues a delivery for every active webhook subscribed to that action, so
no caller has to remember to emit. Deliveries are signed with HMAC-SHA256 and retried a bounded
number of times.

Destinations are checked against private, loopback and link-local addresses. Plain HTTP and
localhost are allowed only in development.
"""

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import Branding, Webhook, WebhookDelivery

MAX_ATTEMPTS = 5
MAX_EVENTS = 40
TIMEOUT_SECONDS = 5.0
ALLOWED_HOSTS_IN_DEV = {"localhost", "127.0.0.1"}


# --- URL safety -------------------------------------------------------------------------------------  # noqa: E501


def validate_url(url: str, settings: Settings) -> None:
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise ValidationFailure("webhook URLs cannot contain credentials")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValidationFailure("webhook URL needs a host")
    local = host in ALLOWED_HOSTS_IN_DEV
    if parts.scheme == "http":
        if not (settings.env == "development" and local):
            raise ValidationFailure("webhook URLs must use https")
    elif parts.scheme != "https":
        raise ValidationFailure("webhook URLs must use https")
    if local and settings.env == "development":
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationFailure("webhook host does not resolve") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValidationFailure("webhook host resolves to a private or reserved address")


# --- management -----------------------------------------------------------------------------------


def create(
    session: Session,
    actor: Principal,
    settings: Settings,
    *,
    name: str,
    url: str,
    events: list[str],
) -> tuple[Webhook, str]:
    validate_url(url, settings)
    if not events or len(events) > MAX_EVENTS:
        raise ValidationFailure(f"subscribe to between 1 and {MAX_EVENTS} events")
    secret = secrets.token_urlsafe(32)
    row = Webhook(
        name=name.strip(),
        url=url,
        events=sorted(set(events)),
        secret=secret,
        active=True,
        created_by=actor.subject,
    )
    session.add(row)
    session.commit()
    return row, secret


def get(session: Session, webhook_id: int) -> Webhook:
    row = session.get(Webhook, webhook_id)
    if row is None:
        raise NotFoundError("webhook not found")
    return row


def describe(row: Webhook) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "events": list(row.events or []),
        "active": row.active,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# --- queueing (called from audit.record) ------------------------------------------------------------  # noqa: E501


def enqueue(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_subject: str,
    details: dict[str, Any] | None,
) -> int:
    hooks = session.scalars(select(Webhook).where(Webhook.active.is_(True))).all()
    queued = 0
    if not hooks:
        return 0
    payload = {
        "event": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor": actor_subject,
        "details": details or {},
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    for hook in hooks:
        if action in (hook.events or []) or "*" in (hook.events or []):
            session.add(WebhookDelivery(webhook_id=hook.id, event=action, payload=payload))
            queued += 1
    return queued


def test_event(session: Session, webhook: Webhook, actor: Principal) -> None:
    session.add(
        WebhookDelivery(
            webhook_id=webhook.id,
            event="webhook.test",
            payload={
                "event": "webhook.test",
                "actor": actor.subject,
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
    )
    session.commit()


# --- delivery -----------------------------------------------------------------------------------------  # noqa: E501


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def dispatch(
    session: Session,
    settings: Settings,
    *,
    limit: int = 100,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, int]:
    rows = session.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.status == "pending")
        .order_by(WebhookDelivery.id)
        .limit(limit)
    ).all()
    delivered = failed = 0
    with httpx.Client(
        transport=transport, timeout=TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        for row in rows:
            hook = session.get(Webhook, row.webhook_id)
            if hook is None or not hook.active:
                row.status = "failed"
                row.last_error = "webhook removed or disabled"
                failed += 1
                continue
            row.attempts += 1
            try:
                validate_url(hook.url, settings)
                body = json.dumps(
                    {"id": row.id, **row.payload}, sort_keys=True, default=str
                ).encode("utf-8")
                timestamp = int(time.time())
                response = client.post(
                    hook.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-ELOR-Event": row.event,
                        "X-ELOR-Delivery": str(row.id),
                        "X-ELOR-Signature": sign(hook.secret, timestamp, body),
                    },
                )
                row.response_code = response.status_code
                if 200 <= response.status_code < 300:
                    row.status = "delivered"
                    row.last_error = None
                    delivered += 1
                    continue
                row.last_error = f"HTTP {response.status_code}"
            except (httpx.HTTPError, ValidationFailure) as exc:
                row.last_error = str(getattr(exc, "message", exc))[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                failed += 1
    session.commit()
    return {
        "delivered": delivered,
        "failed": failed,
        "remaining": session.scalar(
            select(WebhookDelivery.id).where(WebhookDelivery.status == "pending").limit(1)
        )
        is not None,
    }


# --- branding -----------------------------------------------------------------------------------------  # noqa: E501


def branding(session: Session) -> Branding:
    row = session.get(Branding, 1)
    if row is None:
        row = Branding(id=1)
        session.add(row)
        session.flush()
    return row


def set_branding(session: Session, actor: Principal, **fields: Any) -> Branding:
    row = branding(session)
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_by = actor.subject
    row.updated_at = datetime.now(UTC)
    session.commit()
    return row
