"""DEVELOPMENT-ONLY token minting. Imported only by the dev router, which is registered only when
settings.env == "development". Never import this from production code paths.

Keys live in backend/.dev_keys (git-ignored). The API trusts them through OIDC_JWKS_URL=file://...
"""

import json
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.config import BACKEND_DIR, get_settings

KEY_DIR = BACKEND_DIR / ".dev_keys"
PRIVATE_KEY = KEY_DIR / "private.pem"
JWKS_FILE = KEY_DIR / "jwks.json"
KID = "dev-key-1"
ROLES = ("Learner", "Contributor", "Reviewer", "Admin")


def _load_or_create_key():
    KEY_DIR.mkdir(exist_ok=True)
    if PRIVATE_KEY.exists() and JWKS_FILE.exists():
        return serialization.load_pem_private_key(PRIVATE_KEY.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    PRIVATE_KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    JWKS_FILE.write_text(json.dumps({"keys": [jwk]}, indent=2), encoding="utf-8")
    return key


def mint_tokens(hours: float = 24.0) -> dict[str, str]:
    settings = get_settings()
    key = _load_or_create_key()
    now = datetime.now(UTC)
    tokens: dict[str, str] = {}
    for role in ROLES:
        claims = {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "sub": f"dev-{role.lower()}",
            "email": f"{role.lower()}@dev.invalid",
            settings.oidc_roles_claim: [role],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=hours)).timestamp()),
        }
        tokens[role] = jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})
    return tokens


__all__ = ["mint_tokens", "ROLES"]
