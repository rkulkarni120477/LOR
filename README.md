# Enterprise Learning Object Repository (LOR)

A monorepo with a FastAPI backend, a Next.js frontend, LangGraph agents on Amazon Bedrock, and
SQLite storage that can move to PostgreSQL. This is a first runnable version. See
[docs/architecture.md](docs/architecture.md) for the diagram and request flows.

## Quick start (local, no AWS needed)

The current extension adds collections, personal favorites, file version restoration,
authorized downloads, and persisted dashboard metrics. The full enterprise scope and
remaining work are tracked in [the implementation plan](docs/implementation-plan.md).
This checkout remains an incremental development application, not a production release.

Prerequisites: Python 3.12, Node 24, and Docker (optional, for compose).

```powershell
# 1. Environment
Copy-Item .env.example .env          # then edit if needed; .env is git-ignored

# 2. Backend
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head     # creates lor.db
.\.venv\Scripts\python.exe scripts\seed.py             # roles + sample taxonomy
.\.venv\Scripts\python.exe scripts\seed_demo.py        # optional, development only: five courses
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# Health check: http://localhost:8000/health

# 3. Frontend (new terminal)
cd frontend
npm ci
npm run dev                                            # http://localhost:3000

# 4. Dev tokens (LOCAL ONLY; refuses to run unless ENV=development)
cd backend
$env:ENV = "development"; .\.venv\Scripts\python.exe scripts\dev_token_issuer.py --role Contributor
# Paste a token at http://localhost:3000/login
```

On macOS/Linux, use `.venv/bin/python` and `export ENV=development`.

### Make targets (with GNU make)

| Target | What it does |
| --- | --- |
| `make install` | Create the backend venv, install pinned backend deps, run `npm ci` |
| `make dev` | Run backend (8000) and frontend (3000) together |
| `make test` | Backend pytest (offline; AWS tests excluded) |
| `make lint` | Ruff check and format check, then ESLint |
| `make migrate` | `alembic upgrade head` |
| `make seed` | Idempotent seed of roles and taxonomy |
| `make token-dev` | DEV ONLY: print signed tokens for each role |
| `make docker-up` | `docker compose -f infra/docker-compose.yml up --build` |

`make` is not installed by default on Windows. Run the commands in each target directly, as
shown above. `Makefile` documents them.

## Docker

```bash
docker compose -f infra/docker-compose.yml up --build
# Backend:  http://localhost:8000/health
# Frontend: http://localhost:3000
# Through the proxy: http://localhost:3000/api/health
```

Data lives in the `lor-data` volume (`lor.db`, `checkpoints.db`, `vectors.db`, package storage).

## Configuration

All settings come from environment variables or `.env`. Every variable is documented in
[.env.example](.env.example). No secrets are in the repository. AWS credentials come from the
standard AWS chain (environment, profile, or IAM role).

## Repository layout

```
backend/   FastAPI app, Alembic migrations, tests, dev scripts
frontend/  Next.js App Router, Tailwind, API proxy route
infra/     docker-compose.yml, aws/README.md (ECS / App Runner notes)
docs/      architecture.md (Mermaid diagram, request flows, legend)
.vscode/   launch configs for uvicorn and Next.js, recommended extensions, tasks
```

## Status

| Component | Status | Notes |
| --- | --- | --- |
| FastAPI app, `/health`, CORS, JSON logs, global error handler | Implemented | `backend/app/main.py` |
| Config via pydantic-settings | Implemented | `backend/app/core/config.py` |
| SQLAlchemy 2.x models, Alembic initial migration | Implemented | `backend/app/db/`, `backend/migrations/` |
| JWT validation against JWKS, `require_roles` | Implemented | Tested with generated keys. Real IdP needs config |
| Dev token issuer (`ENV=development` only) | Implemented | `backend/scripts/dev_token_issuer.py` |
| Content upload, get, list (pagination, filters) | Implemented | Local storage only |
| Metadata PUT (IEEE LOM subset) | Implemented | Locked after approval |
| Workflow state machine with audit trail | Implemented | Adds `rejected → draft` and a publish step |
| Search with keyword and facet filters | Implemented | Published items only |
| Completions report (Admin) | Implemented | |
| xAPI statements endpoint | Implemented | Accepts one or a list; 400 on malformed input |
| sqlite-vec wrapper | Implemented | Tested with fake embeddings |
| Bedrock factory (ChatBedrock, BedrockEmbeddings) | Implemented, **requires AWS** | Not exercised without credentials |
| Guardrails wrapper | Implemented, off by default | Needs a guardrail created in Bedrock |
| LangGraph ingest supervisor with interrupt and resume | Implemented | Tested with fake LLM |
| Ask router (reporting and search) | Implemented, keyword routing | Claude classifier is a TODO |
| SSE streaming for ask | Implemented, chunked after generation | Not token-level from Bedrock |
| Frontend pages: search, contribute, review, reports | Implemented | |
| Role-aware navigation | Implemented | UX only; backend enforces |
| Next.js proxy with Authorization forwarding | Implemented | Forwards only `/api/health` and `/api/v1/*` |
| Docker images and compose | Implemented | Not run in CI here; see verification notes |
| S3 storage adapter | Implemented, offline contract tested | Set `STORAGE_BACKEND=s3` and `S3_BUCKET`; real AWS not exercised |
| LMS, HR sync, vendor integrations | **Stub** | Documented TODOs |
| Enterprise SSO sign-in (OIDC auth-code + PKCE) | **Requires SSO config** | Paste-a-token sign-in for now |
| AWS deployment (ECS / App Runner) | **Requires AWS config** | Documentation in `infra/aws/README.md` |
| PostgreSQL | **Not yet** | URL is swappable; see the AWS notes |

## Known limitations

- Collections, Favorites, and Versioning have dedicated integrated pages; library and
  recent-object titles open the object detail page for downloads and metadata editing.
- Apply `alembic upgrade head` before running the extended app. The new migration adds
  collections, memberships, favorites, and download events without replacing existing data.
- File restoration retains current metadata and returns the object to draft; the published
  file record is preserved. Full immutable metadata snapshots remain future work.
- Dashboard bytes count distinct storage keys. Downloads are delivery events, not completions.

- SQLite allows one writer. Run a single backend instance, or move to PostgreSQL first.
- Ask answers are generated in one call, then chunked into SSE events.
- The ask router uses keywords, so unusual phrasings may not reach the right template.
- The taxonomy is a small sample. Replace it with your skills framework.
- Package parsing covers zip and SCORM manifests. PDFs are stored and checked for metadata only.
- Role checks use the claim named by `OIDC_ROLES_CLAIM`. Your IdP must emit that claim.
- Admin is a superuser: it passes every role check.
- Make is not available on Windows by default. Use the commands shown above.

## Pinned versions

Backend: `backend/pyproject.toml`. Frontend: `frontend/package.json`. Verified installable on
Python 3.12.10 (Windows) and Node 24.x. Versions the build could not check are noted in the
final handoff summary.
