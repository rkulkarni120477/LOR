from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import httpx
import jwt
import pytest
from sqlalchemy import select

from app.api.v1 import auth
from app.core.permissions import ROLE_PERMISSIONS, Role
from app.core.security import Principal
from app.db.models import AuthSession, LearningObject, OIDCLogin, User
from tests.conftest import StaticKeyProvider


def headers(factory, roles, sub="contrib-1"):
    return {"Authorization": "Bearer " + factory(roles, sub=sub)}


@pytest.mark.parametrize(
    "role,permission,allowed",
    [
        ("Super Administrator", "users.manage", True),
        ("Repository Administrator", "users.manage", False),
        ("Repository Administrator", "content.manage", True),
        ("Content Creator", "content.create", True),
        ("Reviewer", "workflow.review", True),
        ("Reviewer", "workflow.approve", False),
        ("Approver", "workflow.approve", True),
        ("Approver", "workflow.publish", False),
        ("Publisher", "workflow.publish", True),
        ("Instructor", "collections.write", True),
        ("Learner", "content.edit", False),
        ("Read-Only User", "content.download", False),
        ("Read-Only User", "content.read", True),
    ],
)
def test_nine_role_capabilities(role, permission, allowed):
    assert len(ROLE_PERMISSIONS) == 9
    assert Principal(subject="actor", roles=frozenset({role})).can(permission) is allowed


def test_restricted_access_and_immediate_group_revocation(
    client, db_session, token_factory, seeded_lo
):
    admin = headers(token_factory, ["Super Administrator"], "admin")
    owner = headers(token_factory, ["Content Creator"])
    learner = headers(token_factory, ["Learner"], "learner")
    db_session.get(LearningObject, seeded_lo).status = "published"
    db_session.commit()
    assert (
        client.put(
            "/api/v1/admin/users", headers=admin, json={"subject": "learner", "roles": ["Learner"]}
        ).status_code
        == 200
    )
    department = client.post(
        "/api/v1/admin/departments", headers=admin, json={"name": "Research"}
    ).json()["id"]
    group = client.put(
        "/api/v1/admin/groups/0",
        headers=admin,
        json={
            "name": "Research readers",
            "department_id": department,
            "member_subjects": ["learner"],
        },
    ).json()["id"]
    policy = {
        "visibility": "restricted",
        "grants": [{"grantee_type": "group", "grantee_id": str(group), "permission": "read"}],
    }
    assert (
        client.put(f"/api/v1/content/{seeded_lo}/access", headers=owner, json=policy).status_code
        == 200
    )
    assert client.get(f"/api/v1/content/{seeded_lo}", headers=learner).status_code == 200
    assert client.put(f"/api/v1/favorites/{seeded_lo}", headers=learner, json={}).status_code == 200
    assert (
        client.put(
            f"/api/v1/admin/groups/{group}",
            headers=admin,
            json={"name": "Research readers", "member_subjects": []},
        ).status_code
        == 200
    )
    for path in (
        f"/api/v1/content/{seeded_lo}",
        f"/api/v1/content/{seeded_lo}/download",
        f"/api/v1/content/{seeded_lo}/package/files",
    ):
        assert client.get(path, headers=learner).status_code == 404
    assert client.get("/api/v1/search?q=data", headers=learner).json()["total"] == 0
    assert client.get("/api/v1/favorites", headers=learner).json()["total"] == 0
    assert client.get("/api/v1/dashboard", headers=learner).json()["total"] == 0
    assert client.get(f"/api/v1/content/{seeded_lo}", headers=owner).status_code == 200


def test_managed_roles_disabled_accounts_and_admin_escalation(client, token_factory):
    admin = headers(token_factory, ["Super Administrator"], "admin")
    creator = headers(token_factory, ["Content Creator"], "author")
    repository_admin = headers(token_factory, ["Repository Administrator"], "repo-admin")
    assert len(client.get("/api/v1/admin/roles", headers=admin).json()["items"]) == 9
    body = {"subject": "author", "roles": ["Read-Only User"]}
    assert client.put("/api/v1/admin/users", headers=repository_admin, json=body).status_code == 403
    assert client.put("/api/v1/admin/users", headers=admin, json=body).status_code == 200
    assert client.get("/api/v1/auth/me", headers=creator).json()["roles"] == ["Read-Only User"]
    assert (
        client.put(
            "/api/v1/admin/groups/0",
            headers=repository_admin,
            json={"name": "escalation", "roles": ["Super Administrator"]},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/v1/admin/users", headers=admin, json={**body, "disabled": True}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/dashboard", headers=creator).status_code == 403


TENANT = "6f1c2d3e-0000-4000-8000-000000000001"
CLIENT = "9a8b7c6d-1111-4222-8333-444455556666"


def oidc_start(client, settings, monkeypatch):
    settings.oidc_client_id = CLIENT
    settings.oidc_allowed_tenant_id = TENANT
    settings.oidc_allowed_email_domains = ["academian.com"]
    monkeypatch.setattr(
        auth,
        "metadata",
        lambda _: {
            "issuer": settings.oidc_issuer,
            "authorization_endpoint": "https://issuer.test/authorize",
            "token_endpoint": "https://issuer.test/token",
            "jwks_uri": "https://issuer.test/jwks",
        },
    )
    response = client.get("/api/v1/auth/login?next=/collections", follow_redirects=False)
    assert response.status_code == 302
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert "HttpOnly" in response.headers["set-cookie"]
    return params


def oidc_token(settings, rsa_key, nonce):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_client_id,
            "sub": "sso-user",
            "nonce": nonce,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "tid": TENANT,
            "email": "rkulkarni@academian.com",
            "roles": ["Learner"],
        },
        rsa_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_oidc_pkce_cookie_session_and_logout(client, db_session, settings, rsa_key, monkeypatch):
    params = oidc_start(client, settings, monkeypatch)
    login = db_session.scalar(select(OIDCLogin))
    verifier = login.verifier
    post = Mock(
        return_value=httpx.Response(
            200,
            json={"id_token": oidc_token(settings, rsa_key, login.nonce)},
            request=httpx.Request("POST", "https://issuer.test/token"),
        )
    )
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "JWKSKeyProvider", lambda *a, **kw: StaticKeyProvider(rsa_key))
    state = params["state"][0]
    response = client.get(
        f"/api/v1/auth/callback?code=one-use-code&state={state}", follow_redirects=False
    )
    assert response.headers["location"] == settings.app_origin + "/collections"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert post.call_args.kwargs["data"]["code_verifier"] == verifier
    assert client.get("/api/v1/auth/me").json()["roles"] == ["Learner"]
    assert client.get("/api/v1/dashboard").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": settings.app_origin}).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    client.get(f"/api/v1/auth/callback?code=one-use-code&state={state}", follow_redirects=False)
    assert post.call_count == 1


@pytest.mark.parametrize("fault", ["state", "nonce", "expiry"])
def test_oidc_rejects_state_nonce_and_expired_attempt(
    client, db_session, settings, rsa_key, monkeypatch, fault
):
    params = oidc_start(client, settings, monkeypatch)
    attempt = db_session.scalar(select(OIDCLogin))
    if fault == "expiry":
        attempt.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db_session.commit()
    post = Mock(
        return_value=httpx.Response(
            200,
            json={
                "id_token": oidc_token(
                    settings, rsa_key, "wrong" if fault == "nonce" else attempt.nonce
                )
            },
            request=httpx.Request("POST", "https://issuer.test/token"),
        )
    )
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "JWKSKeyProvider", lambda *a, **kw: StaticKeyProvider(rsa_key))
    state = "wrong" if fault == "state" else params["state"][0]
    response = client.get(f"/api/v1/auth/callback?code=code&state={state}", follow_redirects=False)
    assert "sso_error" in response.headers["location"]
    assert db_session.scalar(select(AuthSession)) is None
    if fault != "nonce":
        post.assert_not_called()


def entra_token(settings, rsa_key, nonce, **claims):
    now = datetime.now(UTC)
    body = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_client_id,
        "sub": "entra-user",
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "tid": TENANT,
        "email": "rkulkarni@academian.com",
        "roles": ["Learner"],
    }
    body.update(claims)
    return jwt.encode(body, rsa_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.mark.parametrize(
    "claims,succeeds",
    [
        ({}, True),
        ({"tid": "99999999-0000-4000-8000-000000000009"}, False),
        ({"tid": None}, False),
        ({"email": "someone@gmail.com"}, False),
        ({"email": None, "preferred_username": "rkulkarni@academian.com"}, True),
        ({"email": "x@academian.com.evil.net"}, False),
        ({"email": "a_partner.org#EXT#@academian.com"}, False),
    ],
)
def test_entra_sign_in_is_limited_to_tenant_and_domain(
    client, db_session, settings, rsa_key, monkeypatch, claims, succeeds
):
    settings.oidc_allowed_tenant_id = TENANT
    settings.oidc_allowed_email_domains = ["academian.com"]
    params = oidc_start(client, settings, monkeypatch)
    attempt = db_session.scalar(select(OIDCLogin))
    post = Mock(
        return_value=httpx.Response(
            200,
            json={"id_token": entra_token(settings, rsa_key, attempt.nonce, **claims)},
            request=httpx.Request("POST", "https://issuer.test/token"),
        )
    )
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "JWKSKeyProvider", lambda *a, **kw: StaticKeyProvider(rsa_key))
    response = client.get(
        f"/api/v1/auth/callback?code=code&state={params['state'][0]}", follow_redirects=False
    )
    if succeeds:
        assert response.headers["location"] == settings.app_origin + "/collections"
        assert db_session.scalar(select(AuthSession)) is not None
    else:
        assert "sso_error" in response.headers["location"]
        assert db_session.scalar(select(AuthSession)) is None


def test_sso_refuses_to_start_without_tenant_and_domain_restrictions(client, settings):
    settings.oidc_client_id = "enterprise-client"
    settings.oidc_allowed_tenant_id = ""
    settings.oidc_allowed_email_domains = []
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 503
    assert client.get("/api/v1/auth/config").json()["sso_enabled"] is False


def test_token_sign_in_turns_off_once_entra_is_configured(client, settings):
    settings.env = "development"
    assert client.get("/api/v1/auth/config").json()["development_login"] is True
    settings.oidc_client_id = CLIENT
    settings.oidc_allowed_tenant_id = TENANT
    settings.oidc_allowed_email_domains = ["academian.com"]
    body = client.get("/api/v1/auth/config").json()
    assert body == {"sso_enabled": True, "development_login": False}


def test_placeholder_entra_values_do_not_count_as_configured(client, settings):
    settings.env = "development"
    settings.oidc_client_id = "<application-client-id>"
    settings.oidc_allowed_tenant_id = "<tenant-id>"
    settings.oidc_allowed_email_domains = ["academian.com"]
    assert client.get("/api/v1/auth/config").json() == {
        "sso_enabled": False,
        "development_login": True,
    }
