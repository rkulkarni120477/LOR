"""OIDC code + S256 PKCE sign-in; provider tokens never reach browser JavaScript."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.permissions import canonical, permissions_for
from app.core.security import JWKSKeyProvider, Principal, effective_principal, get_principal
from app.db.models import AuthSession, OIDCLogin, User
from app.db.session import get_db
from app.services import audit
from app.services.users import ensure_user

router = APIRouter(prefix="/auth", tags=["authentication"])


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def secure_url(value, settings):
    url = urlparse(value)
    if url.scheme != "https" and not (
        settings.env in {"development", "test"}
        and url.scheme == "http"
        and url.hostname in {"localhost", "127.0.0.1"}
    ):
        raise HTTPException(503, "OIDC endpoints require HTTPS")
    if url.username or url.password or url.fragment:
        raise HTTPException(503, "Invalid OIDC endpoint configuration")


def verify_organization(claims, settings):
    """Microsoft Entra ID: only the configured tenant, and only the configured email domains.

    Entra puts the directory ID in "tid". Guest accounts from other tenants carry a different
    "tid", so they are refused even when their address looks like an allowed domain.
    """
    if claims.get("tid") != settings.oidc_allowed_tenant_id:
        raise ValueError("tenant not allowed")
    address = str(claims.get("email") or claims.get("preferred_username") or "").lower()
    domain = address.rpartition("@")[2]
    allowed = {d.lower() for d in settings.oidc_allowed_email_domains}
    if "#ext#" in address or not domain or domain not in allowed:
        raise ValueError("email domain not allowed")


def metadata(settings):
    if not settings.oidc_client_id or not settings.oidc_issuer:
        raise HTTPException(503, "Enterprise SSO is not configured")
    if not settings.sso_configured:
        raise HTTPException(
            503, "Enterprise SSO needs OIDC_ALLOWED_TENANT_ID and OIDC_ALLOWED_EMAIL_DOMAINS"
        )
    secure_url(settings.oidc_issuer, settings)
    secure_url(settings.oidc_redirect_uri, settings)
    secure_url(settings.app_origin, settings)
    response = httpx.get(
        settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=5
    )
    response.raise_for_status()
    document = response.json()
    if document.get("issuer") != settings.oidc_issuer:
        raise HTTPException(503, "Identity provider issuer mismatch")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(field):
            raise HTTPException(503, "Incomplete identity provider discovery document")
        secure_url(document[field], settings)
    return document


@router.get("/config")
def config(settings: Settings = Depends(get_settings)):
    return {
        "sso_enabled": settings.sso_configured,
        # Token sign-in is a development fallback. It turns off once Entra SSO is configured.
        "development_login": settings.env == "development" and not settings.sso_configured,
    }


@router.get("/login")
def login(
    next: str = Query("/", max_length=512),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        discovery = metadata(settings)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Identity provider unavailable") from exc
    if (
        not next.startswith("/")
        or next.startswith("//")
        or "\\" in next
        or any(ord(c) < 32 for c in next)
    ):
        raise HTTPException(400, "Invalid return path")
    state, verifier, nonce = (
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(48),
        secrets.token_urlsafe(32),
    )
    now = datetime.now(UTC)
    db.execute(delete(OIDCLogin).where(OIDCLogin.expires_at <= now))
    db.add(
        OIDCLogin(
            state_hash=digest(state),
            verifier=verifier,
            nonce=nonce,
            return_path=next,
            expires_at=now + timedelta(minutes=10),
        )
    )
    db.commit()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": settings.oidc_redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    response = RedirectResponse(
        discovery["authorization_endpoint"] + "?" + urlencode(params), status_code=302
    )
    response.set_cookie(
        "elor_oidc_state",
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.env not in {"development", "test"},
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/callback")
def callback(
    request: Request,
    code: str = Query("", max_length=8192),
    state: str = Query("", max_length=256),
    error: str = Query("", max_length=200),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    failure = RedirectResponse(
        settings.app_origin + "/login?sso_error=sign_in_failed", status_code=302
    )
    failure.delete_cookie("elor_oidc_state", path="/")
    failure.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    browser_state = request.cookies.get("elor_oidc_state", "")
    if not state or not secrets.compare_digest(state, browser_state):
        return failure
    attempt = db.scalar(
        select(OIDCLogin).where(OIDCLogin.state_hash == digest(state)).with_for_update()
    )
    if attempt is None:
        return failure
    verifier, nonce, return_path, expires_at = (
        attempt.verifier,
        attempt.nonce,
        attempt.return_path,
        attempt.expires_at,
    )
    # Consume once, even on a provider failure. No code can be replayed after this commit.
    db.delete(attempt)
    db.commit()
    if error or not code or expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        return failure
    try:
        discovery = metadata(settings)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": settings.oidc_redirect_uri,
            "client_id": settings.oidc_client_id,
        }
        auth = None
        secret = settings.oidc_client_secret.get_secret_value()
        if settings.oidc_token_auth_method != "none" and not secret:
            raise HTTPException(503, "OIDC client secret is not configured")
        if settings.oidc_token_auth_method == "client_secret_basic":
            auth = (settings.oidc_client_id, secret)
        elif settings.oidc_token_auth_method == "client_secret_post":
            data["client_secret"] = secret
        tokens = httpx.post(discovery["token_endpoint"], data=data, auth=auth, timeout=10)
        tokens.raise_for_status()
        document = tokens.json()
        id_token = document["id_token"]
        provider = JWKSKeyProvider(
            discovery["jwks_uri"], settings.oidc_jwks_cache_seconds, allow_file=False
        )
        claims = jwt.decode(
            id_token,
            provider.get_signing_key(id_token),
            algorithms=settings.oidc_algorithms,
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]},
        )
        if not secrets.compare_digest(str(claims["nonce"]), nonce):
            raise ValueError("nonce mismatch")
        verify_organization(claims, settings)
        if (
            isinstance(claims["aud"], list) and len(claims["aud"]) > 1 or "azp" in claims
        ) and claims.get("azp") != settings.oidc_client_id:
            raise ValueError("authorized party mismatch")
        if claims.get("at_hash"):
            algorithm = jwt.get_algorithm_by_name(jwt.get_unverified_header(id_token)["alg"])
            hashed = algorithm.compute_hash_digest(document["access_token"].encode())
            expected = base64.urlsafe_b64encode(hashed[: len(hashed) // 2]).rstrip(b"=").decode()
            if not secrets.compare_digest(expected, claims["at_hash"]):
                raise ValueError("access token hash mismatch")
        raw_roles = claims.get(settings.oidc_roles_claim, [])
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        roles = canonical(raw_roles) or frozenset({"Read-Only User"})
        principal = effective_principal(db, claims["sub"], claims.get("email"), roles)
        user = ensure_user(db, principal)
        token = secrets.token_urlsafe(48)
        expires = datetime.now(UTC) + timedelta(
            seconds=min(max(settings.auth_session_seconds, 60), 28800)
        )
        old = request.cookies.get("elor_session")
        if old:
            db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(old)))
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.now(UTC)))
        db.add(
            AuthSession(
                token_hash=digest(token), user_id=user.id, roles=list(roles), expires_at=expires
            )
        )
        audit.record(
            db,
            actor_subject=principal.subject,
            action="auth.login",
            entity_type="user",
            entity_id=str(user.id),
        )
        db.commit()
    except (HTTPException, httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError, TypeError):
        db.rollback()
        return failure
    response = RedirectResponse(settings.app_origin + return_path, status_code=302)
    response.set_cookie(
        "elor_session",
        token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=settings.env not in {"development", "test"},
        max_age=int((expires - datetime.now(UTC)).total_seconds()),
    )
    response.delete_cookie("elor_oidc_state", path="/")
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return response


@router.get("/me")
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ensure_user(db, principal)
    return {
        "subject": principal.subject,
        "email": principal.email,
        "roles": sorted(canonical(principal.roles)),
        "permissions": sorted(permissions_for(principal.roles)),
        "group_ids": sorted(principal.group_ids),
        "department_ids": sorted(principal.department_ids),
        "expires_at": principal.expires_at,
    }


@router.post("/logout")
def logout(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    if request.headers.get("origin") != settings.app_origin:
        raise HTTPException(403, "A same-origin request is required")
    token = request.cookies.get("elor_session")
    if token:
        row = db.get(AuthSession, digest(token))
        if row:
            user = db.get(User, row.user_id)
            audit.record(
                db,
                actor_subject=user.subject,
                action="auth.logout",
                entity_type="user",
                entity_id=str(user.id),
            )
            db.delete(row)
            db.commit()
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie("elor_session", path="/")
    return response
