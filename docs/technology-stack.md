# Requested technology stack

## Frontend

React and TypeScript continue to run in the existing Next.js host. React Router now
owns all page navigation and browser history. Next.js serves one catch-all shell and
the existing authenticated API proxy; it no longer defines individual product routes.
Views live in `frontend/views`, and route definitions in `components/Application.tsx`.
Deep links and refreshes are served by the catch-all shell.

The application has one MUI theme. Collections, favorites and versioning use MUI
forms, alerts, cards, controls and loading states. The collection creation form uses
React Hook Form validation. These screens use TanStack Query for reads, mutations
and invalidation. A new QueryClient is created when the session changes so cached
data never crosses identities. Reports use TanStack Query and Recharts; the accessible
data table remains alongside the chart. Existing dashboard styling is retained.

## Local service stack

The lightweight SQLite configuration is retained. To run PostgreSQL, Redis,
OpenSearch and Celery together, from the repository root:

```powershell
docker compose -f infra/docker-compose.yml -f infra/docker-compose.stack.yml up --build -d
docker compose -f infra/docker-compose.yml -f infra/docker-compose.stack.yml exec backend python scripts/seed.py
docker compose -f infra/docker-compose.yml -f infra/docker-compose.stack.yml exec backend python scripts/seed_demo.py
docker compose -f infra/docker-compose.yml -f infra/docker-compose.stack.yml exec backend python scripts/reindex.py
```

Copy `.env.example` to `.env` first if missing. Existing `.env` files are not replaced.
The stack overlay selects PostgreSQL and OpenSearch regardless of SQLite settings in
the local environment file. Migrations run before the API starts. Data volumes for
PostgreSQL, Redis and OpenSearch are separate from the original SQLite volume;
existing SQLite data is not automatically migrated or erased.

| Service | Host endpoint | Purpose |
| --- | --- | --- |
| Frontend | http://localhost:3000 | React Router application |
| API | http://localhost:8000/docs | REST API/OpenAPI |
| PostgreSQL | 127.0.0.1:55432 | Repository database |
| Redis | 127.0.0.1:56379 | Celery broker (DB 0), task results (DB 1) |
| OpenSearch | http://127.0.0.1:59200 | Published metadata full-text index |
| Worker | Internal | Applies search projections |
| Beat | Internal, one instance | Dispatches pending indexing every ten seconds |

The sample PostgreSQL password `elor-local-only` and disabled OpenSearch security
are strictly for local development on loopback. For production, use managed secrets,
private networks, TLS, authenticated OpenSearch and Redis, managed PostgreSQL, and
replicated search indices. This file does not provision AWS infrastructure.
Allow several GB of Docker memory for OpenSearch. On Linux, OpenSearch may require
`vm.max_map_count=262144` on the host; configure this according to your host policy.

## Running the backend directly against the containers

From `backend` in PowerShell:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://elor:elor-local-only@localhost:55432/elor'
$env:REDIS_URL = 'redis://localhost:56379/0'
$env:CELERY_RESULT_BACKEND = 'redis://localhost:56379/1'
$env:SEARCH_BACKEND = 'opensearch'
$env:OPENSEARCH_URL = 'http://localhost:59200'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Use the same environment in worker and beat terminals:

```powershell
.\.venv\Scripts\python.exe -m celery -A app.worker:celery_app worker --pool=solo --loglevel=INFO
.\.venv\Scripts\python.exe -m celery -A app.worker:celery_app beat --loglevel=INFO
```

Windows uses the solo pool; Linux containers use the default prefork pool. Run only
one beat scheduler per deployment. Redis uses AOF persistence and no eviction to
protect queued jobs. Celery accepts JSON only, uses late acknowledgement and bounds
task execution time. `/health` is liveness; `/health/ready` checks the database and,
when OpenSearch is enabled, Redis and OpenSearch. Readiness does not prove a worker
is running; the Compose worker healthcheck separately pings its worker node.

## Index consistency and recovery

Create, metadata update, workflow transition and file restoration enqueue a row in
`search_index_jobs` in the content transaction. A broker outage cannot lose that row.
Celery processes committed rows, retries failed projections with backoff, and deletes
successful jobs. PostgreSQL `SKIP LOCKED` allows cooperating workers. Replays are
idempotent; unpublished objects are removed from the index. An index outage cannot
roll back a successful content mutation.

Full-text queries use OpenSearch candidate IDs; publication, facet counts and result
metadata are rechecked against current database records. Empty-query browsing works
from SQL. Search indexing is eventually consistent, so newly published content can
take a scheduler interval to appear. Full-text requests return 503 if search is down.
Current candidate IDs are materialized before SQL filtering; very large repositories
will need a PIT-based search pagination contract to avoid large candidate sets.

`scripts/reindex.py` queues all current objects for rebuilding a new or recovered
index. Failed jobs remain in the database with attempt count and next retry time.
The worker logs failures with the learning object ID, without connection secrets.

## Checks

Verified in this workspace: 76 backend tests on SQLite, the same 76 on PostgreSQL,
three frontend component tests, TypeScript checking, and a production build. The live
service smoke check passed against PostgreSQL, Redis, OpenSearch and a real Celery
worker. The three dependency containers were healthy after verification.

```powershell
# Backend (SQLite, offline)
cd backend
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

# Existing backend suite against a disposable PostgreSQL database
# Create a separate database whose name ends in _test; the suite resets its tables.
$env:ELOR_TEST_DATABASE_URL = 'postgresql+psycopg://elor:elor-local-only@localhost:55432/elor_test'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

# Frontend, from frontend/
npm run test
npm run typecheck
npm run build
```

PostgreSQL integration tests refuse any database name that does not end in `_test`.
Never point that variable at application data. Dependency versions are pinned in
`backend/pyproject.toml` and `frontend/package.json`/`package-lock.json`.

For an end-to-end service check, create a separate disposable `elor_stack_test`
database, configure `DATABASE_URL` to it, use Redis databases 14/15 for the test
broker/results, and set `OPENSEARCH_INDEX=elor-test-smoke`. Then run
`python scripts/check_stack.py` from `backend`. The script applies real migrations,
starts and stops its own solo Celery worker on a unique queue, publishes a test
object, verifies full-text search, verifies immediate publication revocation, and
removes its test index and learning object. Do not run the PostgreSQL suite and this
smoke check concurrently against the same database.

Implementation references: [React Router BrowserRouter](https://reactrouter.com/api/declarative-routers/BrowserRouter),
[TanStack queries](https://tanstack.com/query/latest/docs/framework/react/guides/queries),
[OpenSearch Python client](https://docs.opensearch.org/latest/clients/python-low-level/),
and [Celery periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).
