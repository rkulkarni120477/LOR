"""OIDC/JWT validation against the issuer's JWKS, plus role checks.

- Keys are fetched from settings.oidc_jwks_url and cached for oidc_jwks_cache_seconds.
- Signature, issuer, audience, and expiry are validated by PyJWT.
- Roles are read from the claim named by settings.oidc_roles_claim.
- Admin satisfies every role requirement (superuser). Documented in docs/architecture.md.
- file:// JWKS URLs are accepted ONLY when ENV=development (dev token issuer).
"""

import hashlib
import json
import threading
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, Settings, get_settings
from app.core.permissions import ROLE_ALIASES, Role, canonical, permissions_for
from app.db.models import AuthSession, Group, GroupMember, GroupRole, User, UserRole
from app.db.models import Role as RoleRow
from app.db.session import get_db

KNOWN_ROLES = {r.value for r in Role} | set(ROLE_ALIASES)


class Principal(BaseModel):
    subject: str
    email: str | None = None
    roles: frozenset[str] = Field(default_factory=frozenset)
    group_ids: frozenset[int] = Field(default_factory=frozenset)
    department_ids: frozenset[int] = Field(default_factory=frozenset)
    expires_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return bool(canonical(self.roles) & {Role.SUPER_ADMIN.value, Role.REPOSITORY_ADMIN.value})

    def can(self, permission: str) -> bool:
        permissions = permissions_for(self.roles)
        return "*" in permissions or permission in permissions

    def has_any(self, required: set[str]) -> bool:
        if Role.SUPER_ADMIN.value in canonical(self.roles):
            return True
        return bool(canonical(self.roles) & canonical(required))


class SigningKeyProvider(Protocol):
    def get_signing_key(self, token: str): ...


class JWKSKeyProvider:
    """Fetches and caches the issuer JWKS. Refetches once when a token's kid is unknown."""

    def __init__(self, jwks_url: str, cache_seconds: int, allow_file: bool) -> None:
        self._url = jwks_url
        self._ttl = cache_seconds
        self._allow_file = allow_file
        self._cache: jwt.PyJWKSet | None = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _load_document(self) -> dict:
        if not self._url:
            raise RuntimeError("OIDC_JWKS_URL is not configured")
        if self._url.startswith("file://"):
            if not self._allow_file:
                raise RuntimeError("file:// JWKS is only allowed when ENV=development")
            path = Path(self._url.removeprefix("file://"))
            if not path.is_absolute():
                path = BACKEND_DIR / path
            return json.loads(path.read_text(encoding="utf-8"))
        response = httpx.get(self._url, timeout=5.0)
        response.raise_for_status()
        return response.json()

    def _jwks(self, force: bool = False) -> jwt.PyJWKSet:
        with self._lock:
            fresh = self._cache is not None and (time.monotonic() - self._fetched_at) < self._ttl
            if force or not fresh:
                self._cache = jwt.PyJWKSet.from_dict(self._load_document())
                self._fetched_at = time.monotonic()
            return self._cache

    def get_signing_key(self, token: str):
        kid = jwt.get_unverified_header(token).get("kid")
        for attempt in (False, True):  # second pass forces a refresh for rotated keys
            for key in self._jwks(force=attempt).keys:
                if kid is None or key.key_id == kid:
                    return key.key
        raise jwt.PyJWTError("no signing key matches token kid")


@lru_cache
def get_key_provider() -> JWKSKeyProvider:
    settings = get_settings()
    return JWKSKeyProvider(
        settings.oidc_jwks_url,
        settings.oidc_jwks_cache_seconds,
        allow_file=settings.env == "development",
    )


def decode_token(token: str, provider: SigningKeyProvider, settings: Settings) -> dict:
    """Validate signature, issuer, audience, expiry. Raises jwt.PyJWTError subclasses."""
    key = provider.get_signing_key(token)
    return jwt.decode(
        token,
        key,
        algorithms=settings.oidc_algorithms,
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
        options={"require": ["exp", "sub", "iss", "aud"]},
    )


_bearer = HTTPBearer(auto_error=False)


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    provider: SigningKeyProvider = Depends(get_key_provider),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Principal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        token = request.cookies.get("elor_session")
        row = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
        if row is None or row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
            raise unauthorized
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("origin") != settings.app_origin
        ):
            raise HTTPException(403, "A same-origin request is required")
        user = db.get(User, row.user_id)
        if user is None:
            raise unauthorized
        return effective_principal(
            db, user.subject, user.email, frozenset(row.roles), row.expires_at
        )
    try:
        claims = decode_token(credentials.credentials, provider, settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token rejected: {type(exc).__name__}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider unavailable",
        ) from exc

    raw_roles = claims.get(settings.oidc_roles_claim, [])
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = frozenset(r for r in raw_roles if r in KNOWN_ROLES)
    return effective_principal(
        db, claims["sub"], claims.get("email"), roles, datetime.fromtimestamp(claims["exp"], UTC)
    )


def effective_principal(db, subject, email, roles, expires_at=None):
    user = db.scalar(select(User).where(User.subject == subject))
    groups = []
    departments = set()
    if user:
        if user.disabled:
            raise HTTPException(403, "This account is disabled")
        groups = list(
            db.scalars(select(Group).join(GroupMember).where(GroupMember.user_id == user.id))
        )
        if user.department_id:
            departments.add(user.department_id)
        departments.update(g.department_id for g in groups if g.department_id is not None)
        if user.roles_managed:
            roles = frozenset(
                db.scalars(select(RoleRow.name).join(UserRole).where(UserRole.user_id == user.id))
            )
        if groups:
            roles = roles | frozenset(
                db.scalars(
                    select(RoleRow.name)
                    .join(GroupRole)
                    .where(GroupRole.group_id.in_([g.id for g in groups]))
                )
            )
    return Principal(
        subject=subject,
        email=email,
        roles=roles,
        expires_at=expires_at,
        group_ids=frozenset(g.id for g in groups),
        department_ids=frozenset(departments),
    )


def require_permission(permission: str):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(permission):
            raise HTTPException(403, f"Requires permission: {permission}")
        return principal

    return dependency


def require_roles(*roles: Role | str):
    """Route dependency: allows the request only if the caller holds at least one role."""
    required = {r.value if isinstance(r, Role) else r for r in roles}

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has_any(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(sorted(required))}",
            )
        return principal

    return dependency
