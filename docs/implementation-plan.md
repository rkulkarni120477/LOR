# ELOR implementation plan and API contract

## Architecture and repository structure

The existing checkout contains React 19 with TypeScript in Next.js (`frontend/app`,
`frontend/components`, `frontend/lib`), FastAPI (`backend/app/api/v1`), SQLAlchemy
models (`backend/app/db`), domain services (`backend/app/services`), Alembic
migrations (`backend/migrations`), and offline tests (`backend/tests`). Preserve
working code and local UI edits while extending these boundaries.

The target production topology is CloudFront/WAF -> frontend and API ECS services
in private subnets -> RDS PostgreSQL, Redis, OpenSearch and private S3. Cognito
provides verified JWTs; ECS task roles access Bedrock, S3 and Secrets Manager.
Celery workers process quarantined uploads before objects become reviewable.
This topology is a target, not a statement of deployed infrastructure.

## Schema

Existing: users, roles, user_roles, learning_objects, versions, metadata_lom,
taxonomy_terms, workflow_states, audit_log, xapi_statements. Versions have a
unique (lo_id, version_number); metadata has a unique lo_id. Workflow and audit
history are append-only by application convention.

Increment: collections (UUID, name, description, owner subject, visibility),
collection_items (collection and object foreign keys, composite primary key,
position), favorites (subject and object composite primary key, folder), downloads
(object foreign key, version, actor, time). Collection deletion cascades membership,
never content. Identity subjects match verified OIDC subjects. All added mutations
write audit records in the same transaction.

Remaining normalized entities: departments, permissions, object ACLs, content_files,
metadata_schemas and values, tags and object_tags, workflow templates/instances/tasks,
reviews, version-specific approvals, notifications, integrations and usage_events.
Add these with reviewed migrations, not unversioned startup create_all calls.

The technology-stack extension adds `search_index_jobs` with learning object ID,
attempt count, created time, and indexed next-attempt time. It deliberately retains
jobs after an object is removed so a worker can delete its stale search projection.

## API contract

All paths below are under `/api/v1`; authenticated bearer token required. Runtime
OpenAPI at `/openapi.json` and Swagger at `/docs` are the executable contract.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | /dashboard | Visibility-scoped counts, bytes, downloads, recent objects |
| GET, POST | /collections | Paginated visible collections; contributor creates |
| GET, PUT, DELETE | /collections/{id} | Read visible collection; owner/admin mutates |
| PUT | /collections/{id}/items | Atomically replace ordered object IDs |
| GET | /favorites/folders | Default personal folder choices |
| GET | /favorites | Paginated personal accessible objects; folder/query filter |
| PUT, DELETE | /favorites/{lo_id} | Idempotently save/move or remove own favorite |
| GET | /content/{id}/download | Authorized attachment, optional version query |
| POST | /content/{id}/versions/{number}/restore | Owner/admin creates new draft version |

Errors: 401 missing/invalid identity, 403 insufficient role/ownership, 404 absent
or hidden object, 409 conflicting mutation, 422 invalid request. Collection reads
and favorite reads always recheck current content visibility. Paginated lists
use page >= 1 and page_size 1..100. Downloads are delivery events, never learning
completions. Storage bytes count distinct underlying storage keys.

## Sequential execution and acceptance gates

1. Foundation: preserve verified JWT/RBAC and existing migration; run offline
   tests. Remaining: nine-role permission matrix, departments/groups, real OIDC
   redirect login and PostgreSQL CI. The requested frontend libraries and local
   PostgreSQL/Redis/OpenSearch/Celery integration are implemented; see technology-stack.md.
2. Core: existing upload/library; add persisted collections, favorites, download
   events and metrics with integrated pages. Remaining: standalone creation editor,
   multipart quarantined uploads, all listed formats, advanced saved search,
   object editing/duplication/deletion and richer detail pages.
3. Governance: existing audited review transitions; add append-only restoration.
   Remaining: immutable published snapshots including metadata, separate approver
   and publisher permissions, version-specific approvals, configurable workflows,
   taxonomy/schema UI, admin policies and notifications.
4. Intelligence/integrations: retain Bedrock and xAPI groundwork. Remaining:
   editable AI authoring, configured Moodle/CAS/LRS adapters, event-based analytics,
   additional charts, scheduled reports and all export formats. Reports now include
   a Recharts completion chart with its data table.
5. Production: remaining Terraform, managed-service deployment,
   scanner quarantine, rate limits, backup/recovery, observability, expanded component and
   Playwright/a11y tests, load tests, security review and actual AWS deployment.

Each gate requires runnable code, migrations, permission/failure tests and setup
instructions. The current increment does not satisfy the full enterprise brief
and must not be represented as production ready.
