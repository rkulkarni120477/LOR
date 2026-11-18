"""Shared fixtures. Everything runs offline: in-memory SQLite, generated RSA keys, fake storage."""

import io
import sys
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.deps import get_storage  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.security import get_key_provider  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import LearningObject, MetadataLOM, Version  # noqa: E402
from app.db.session import get_db, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage.local import LocalStorage  # noqa: E402

ISSUER = "https://issuer.test"
AUDIENCE = "lor-api"
KID = "test-key"


class FakeLLM:
    """Stands in for ChatBedrock. Records prompts and returns a canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


class FakeEmbeddings:
    """Deterministic bag-of-words embedding into 8 dimensions. No AWS required."""

    DIMS = 8

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.DIMS
        for token in text.lower().split():
            vec[sum(map(ord, token)) % self.DIMS] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeyProvider:
    def __init__(self, key) -> None:
        self._public = key.public_key()

    def get_signing_key(self, token: str):
        return self._public


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url="sqlite:///:memory:",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url="https://issuer.test/jwks",
        local_storage_path=str(tmp_path / "storage"),
        vector_db_path=":memory:",
        checkpoint_db_path=":memory:",
        compliance_threshold=0.7,
    )


@pytest.fixture
def token_factory(rsa_key):
    def make(
        roles: list[str],
        sub: str = "user-1",
        *,
        audience: str = AUDIENCE,
        issuer: str = ISSUER,
        expires_in: timedelta = timedelta(hours=1),
        email: str | None = None,
    ) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": sub,
            "roles": roles,
            "iat": int(now.timestamp()),
            "exp": int((now + expires_in).timestamp()),
        }
        if email:
            claims["email"] = email
        return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": KID})

    return make


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()


@pytest.fixture
def seeded_lo(db_session):
    """One learning object with a version and a metadata row."""
    lo_id = str(uuid.uuid4())
    lo = LearningObject(id=lo_id, title="Intro to Data", status="draft", created_by="contrib-1")
    lo.versions.append(
        Version(
            version_number=1,
            storage_key=f"{lo_id}/v1/pkg.zip",
            original_filename="pkg.zip",
            content_type="application/zip",
            size_bytes=10,
            sha256="0" * 64,
            created_by="contrib-1",
        )
    )
    lo.metadata_record = MetadataLOM(title="Intro to Data", keywords=["data"], lom_json={})
    db_session.add(lo)
    db_session.commit()
    return lo_id


@pytest.fixture
def client(settings, engine, tmp_path, rsa_key):
    app = create_app(settings)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_key_provider] = lambda: StaticKeyProvider(rsa_key)
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "storage")
    with TestClient(app) as test_client:
        yield test_client


def build_package(
    *,
    images: list[tuple[str, str]] | None = None,
    license_text: str | None = "CC-BY-4.0",
    video: bool = False,
    captions: bool = False,
) -> bytes:
    """Build a SCORM-like zip. images: list of (src, alt); alt "" means missing alt text."""
    buffer = io.BytesIO()
    body = "<html><head><title>Data Basics</title></head><body><p>Learn data.</p>"
    for src, alt in images or []:
        body += f'<img src="{src}" alt="{alt}"/>'
    body += "</body></html>"
    manifest = "<manifest><metadata>"
    if license_text:
        manifest += f"<license>{license_text}</license>"
    manifest += "</metadata><title>Data Basics</title></manifest>"
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("index.html", body)
        archive.writestr("imsmanifest.xml", manifest)
        if video:
            archive.writestr("media/intro.mp4", b"fake-video")
        if captions:
            archive.writestr("media/intro.vtt", "WEBVTT\n")
    return buffer.getvalue()


@pytest.fixture
def package_bytes():
    return build_package(images=[("a.png", "Chart of sales")], license_text="CC-BY-4.0")


@pytest.fixture
def fake_embeddings():
    return FakeEmbeddings()


@pytest.fixture
def fake_llm_factory():
    def factory(response: str):
        llm = FakeLLM(response)
        return llm, (lambda: llm)

    return factory
