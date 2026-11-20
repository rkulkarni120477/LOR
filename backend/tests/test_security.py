"""Phase 3: OIDC/JWT validation and role checks."""

from datetime import timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import (
    JWKSKeyProvider,
    Principal,
    Role,
    get_key_provider,
    get_principal,
    require_roles,
)
from tests.conftest import AUDIENCE, ISSUER, StaticKeyProvider
from app.db.session import get_db


@pytest.fixture
def auth_app(settings, rsa_key, db_session):
    app = FastAPI()

    @app.get("/whoami")
    def whoami(principal: Principal = Depends(get_principal)):
        return {"sub": principal.subject, "roles": sorted(principal.roles)}

    @app.get("/contributor-only")
    def contributor_only(principal: Principal = Depends(require_roles(Role.CONTRIBUTOR))):
        return {"ok": True}

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_key_provider] = lambda: StaticKeyProvider(rsa_key)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_is_accepted(auth_app, token_factory):
    token = token_factory(["Contributor"], sub="alice")
    response = auth_app.get("/whoami", headers=_auth(token))
    assert response.status_code == 200
    assert response.json() == {"sub": "alice", "roles": ["Contributor"]}


def test_expired_token_is_rejected(auth_app, token_factory):
    token = token_factory(["Contributor"], expires_in=timedelta(seconds=-60))
    response = auth_app.get("/whoami", headers=_auth(token))
    assert response.status_code == 401


def test_wrong_audience_is_rejected(auth_app, token_factory):
    token = token_factory(["Contributor"], audience="someone-else")
    response = auth_app.get("/whoami", headers=_auth(token))
    assert response.status_code == 401


def test_wrong_issuer_is_rejected(auth_app, token_factory):
    token = token_factory(["Contributor"], issuer="https://evil.example")
    response = auth_app.get("/whoami", headers=_auth(token))
    assert response.status_code == 401


def test_missing_token_is_rejected(auth_app):
    assert auth_app.get("/whoami").status_code == 401


def test_missing_role_returns_403(auth_app, token_factory):
    token = token_factory(["Learner"])
    response = auth_app.get("/contributor-only", headers=_auth(token))
    assert response.status_code == 403


def test_required_role_returns_200(auth_app, token_factory):
    token = token_factory(["Contributor"])
    assert auth_app.get("/contributor-only", headers=_auth(token)).status_code == 200


def test_admin_satisfies_any_role_requirement(auth_app, token_factory):
    token = token_factory(["Admin"])
    assert auth_app.get("/contributor-only", headers=_auth(token)).status_code == 200


def test_file_jwks_refused_outside_development(tmp_path):
    jwks = tmp_path / "jwks.json"
    jwks.write_text('{"keys": []}')
    provider = JWKSKeyProvider(f"file://{jwks}", cache_seconds=60, allow_file=False)
    with pytest.raises(RuntimeError, match="only allowed when ENV=development"):
        provider.get_signing_key(jwt.encode({}, "x" * 32, algorithm="HS256"))


def test_jwks_fetched_from_file_in_development(tmp_path, rsa_key):
    import json

    from jwt.algorithms import RSAAlgorithm

    jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    jwks = tmp_path / "jwks.json"
    jwks.write_text(json.dumps({"keys": [jwk]}))

    provider = JWKSKeyProvider(f"file://{jwks}", cache_seconds=60, allow_file=True)
    token = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": 4102444800},
        rsa_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    key = provider.get_signing_key(token)
    decoded = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)
    assert decoded["sub"] == "x"
