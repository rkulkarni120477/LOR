"""In-app notifications and queued email.

Every notification is stored in the app. Email for the same event is queued in email_outbox and
sent by dispatch(), which runs on demand (POST /notifications/dispatch) or from a scheduler.
Without SMTP configuration, mail stays queued and nothing is lost.
"""

import smtplib
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.permissions import ROLE_PERMISSIONS
from app.db.models import (
    EmailOutbox,
    GroupMember,
    GroupRole,
    Notification,
    Role,
    User,
    UserRole,
    utcnow,
)

MAX_ATTEMPTS = 5
POOL_LIMIT = 200


class MailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        s = self._settings
        message = EmailMessage()
        message["From"] = s.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as client:
            if s.smtp_starttls:
                client.starttls()
            if s.smtp_user:
                client.login(s.smtp_user, s.smtp_password.get_secret_value())
            client.send_message(message)


def build_sender(settings: Settings) -> MailSender | None:
    return SmtpSender(settings) if settings.smtp_host else None


def _roles_with(permission: str) -> list[str]:
    return [name for name, perms in ROLE_PERMISSIONS.items() if permission in perms or "*" in perms]


def _users_holding(db: Session, role_names: list[str]) -> list[User]:
    """Users who hold a role directly or through a group. Disabled users are excluded."""
    direct = (
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name.in_(role_names))
    )
    via_group = (
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .join(GroupRole, GroupRole.group_id == GroupMember.group_id)
        .join(Role, Role.id == GroupRole.role_id)
        .where(Role.name.in_(role_names))
    )
    users: dict[int, User] = {}
    for user in list(db.scalars(direct)) + list(db.scalars(via_group)):
        if not user.disabled:
            users[user.id] = user
    return list(users.values())[:POOL_LIMIT]


def permission_holders(db: Session, permission: str) -> list[str]:
    return [u.subject for u in _users_holding(db, _roles_with(permission))]


def role_holders(db: Session, role_name: str) -> list[str]:
    return [u.subject for u in _users_holding(db, [role_name])]


def notify(
    db: Session,
    subjects: list[str],
    *,
    kind: str,
    title: str,
    body: str = "",
    lo_id: str | None = None,
    app_name: str = "ELOR",
) -> int:
    """Stores an in-app notification for each subject and queues email where an address is known."""
    count = 0
    for subject in dict.fromkeys(subjects):
        db.add(
            Notification(recipient_subject=subject, kind=kind, title=title, body=body, lo_id=lo_id)
        )
        user = db.scalar(select(User).where(User.subject == subject))
        if user is not None and user.email and not user.disabled:
            db.add(
                EmailOutbox(
                    recipient_email=user.email,
                    subject=f"[{app_name}] {title}",
                    body=f"{body}\n\nOpen the item in {app_name} to act on it.",
                )
            )
        count += 1
    return count


def dispatch(db: Session, sender: MailSender | None, limit: int = 100) -> dict[str, int | str]:
    if sender is None:
        pending = db.scalar(select(EmailOutbox.id).where(EmailOutbox.status == "pending").limit(1))
        return {
            "sent": 0,
            "failed": 0,
            "note": "SMTP is not configured" if pending else "nothing queued",
        }
    sent = failed = 0
    rows = db.scalars(
        select(EmailOutbox)
        .where(EmailOutbox.status == "pending")
        .order_by(EmailOutbox.id)
        .limit(limit)
    ).all()
    for row in rows:
        row.attempts += 1
        try:
            sender.send(row.recipient_email, row.subject, row.body)
        except (OSError, smtplib.SMTPException) as exc:
            row.last_error = str(exc)[:1000]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
            failed += 1
        else:

            row.status = "sent"
            row.sent_at = utcnow()
            row.last_error = None
            sent += 1
    db.commit()
    return {"sent": sent, "failed": failed}
