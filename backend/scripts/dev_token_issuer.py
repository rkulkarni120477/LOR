"""DEVELOPMENT-ONLY token issuer. NEVER run this in production.

It generates an RSA key pair under backend/.dev_keys (git-ignored), writes a JWKS file, and signs
tokens for each role. The API trusts that JWKS only when ENV=development (see OIDC_JWKS_URL=file://...).

Usage (from backend/):
    ENV=development python scripts/dev_token_issuer.py                 # one token per role
    ENV=development python scripts/dev_token_issuer.py --role Reviewer --hours 2
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402

from app.core.config import get_settings  # noqa: E402

KEY_DIR = BACKEND_DIR / ".dev_keys"
PRIVATE_KEY = KEY_DIR / "private.pem"
JWKS_FILE = KEY_DIR / "jwks.json"
KID = "dev-key-1"
ROLES = ("Learner", "Contributor", "Reviewer", "Admin")


def guard() -> None:
    env = get_settings().env
    if env != "development":
        sys.exit(f"Refusing to run: ENV must be 'development' (current: {env!r}).")


def ensure_keys():
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


def issue(private_key, role: str, hours: float, subject: str | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": subject or f"dev-{role.lower()}",
        "email": f"{role.lower()}@dev.invalid",
        settings.oidc_roles_claim: [role],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})


def main() -> None:
    guard()
    parser = argparse.ArgumentParser(description="DEV ONLY: sign tokens for local testing")
    parser.add_argument("--role", choices=ROLES, help="issue only this role")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--subject", help="override the sub claim (single role only)")
    args = parser.parse_args()

    key = ensure_keys()
    roles = [args.role] if args.role else list(ROLES)
    print("# DEV ONLY. Do not use these tokens anywhere except a local machine.")
    for role in roles:
        token = issue(key, role, args.hours, args.subject if args.role else None)
        print(f"{role}={token}")


if __name__ == "__main__":
    main()
