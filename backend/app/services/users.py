from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import Principal
from app.db.models import User


def ensure_user(session: Session, principal: Principal) -> User:
    """Create or refresh the local user row for an authenticated principal.

    TODO: sync role assignments into roles/user_roles. Roles currently come from the token
    claim on every request; the tables exist for reporting and future admin tooling.
    """
    user = session.scalar(select(User).where(User.subject == principal.subject))
    if user is None:
        user = User(subject=principal.subject, email=principal.email)
        session.add(user)
    elif principal.email and user.email != principal.email:
        user.email = principal.email
    session.commit()
    return user
