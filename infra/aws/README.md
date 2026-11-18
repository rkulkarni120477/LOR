# AWS deployment (ECS Fargate or App Runner)

Status: **documentation only.** Nothing here has been deployed. Deploying needs an AWS account,
Bedrock model access, and (for sign-in) an enterprise OIDC client. None of these are available
in this repository.

## 1. Choose the runtime

| Option | Use when | Notes |
| --- | --- | --- |
| **ECS Fargate, one task, EFS volume** | SQLite stays for now | Simplest path for SQLite. Mount EFS at `/srv/data` so `lor.db` and `checkpoints.db` persist. Run **one task** only: SQLite allows a single writer. |
| **App Runner** | Stateless deployment, PostgreSQL already in place | App Runner has no volume mounts, so SQLite does not fit. Use it after the move to RDS or Aurora. |

## 2. Images

```bash
aws ecr create-repository --repository-name lor-backend
aws ecr create-repository --repository-name lor-frontend
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com
docker build -t lor-backend ./backend
docker build -t lor-frontend ./frontend
docker tag lor-backend <acct>.dkr.ecr.<region>.amazonaws.com/lor-backend:<tag>
docker push <acct>.dkr.ecr.<region>.amazonaws.com/lor-backend:<tag>
```

## 3. IAM

**Task execution role** (pulls images, writes logs): `AmazonECSTaskExecutionRolePolicy`.

**Task role** (what the app calls at runtime):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeBedrockModels",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:<region>::foundation-model/anthropic.claude-*",
        "arn:aws:bedrock:<region>::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:<region>:<acct>:inference-profile/us.anthropic.claude-*"
      ]
    },
    {
      "Sid": "ApplyGuardrailIfEnabled",
      "Effect": "Allow",
      "Action": ["bedrock:ApplyGuardrail"],
      "Resource": "arn:aws:bedrock:<region>:<acct>:guardrail/<guardrail-id>"
    },
    {
      "Sid": "PackageBucketIfS3Enabled",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<bucket>/*"
    }
  ]
}
```

- Include the `s3:*` statement only when the S3 adapter is implemented and enabled.
  `backend/app/storage/s3.py` is a stub today.
- Drop `ApplyGuardrailIfEnabled` if `GUARDRAILS_ENABLED=false`.
- Check the exact Claude model ID and inference profile in the Bedrock console for your region,
  and enable model access there first. Model access is not granted by IAM alone.

## 4. Configuration

Set these as task environment variables or pull them from SSM Parameter Store / Secrets Manager.
Do not bake them into the image. See `.env.example` for the full list.

Required for production:

- `ENV=production`
- `OIDC_ISSUER`, `OIDC_JWKS_URL` (https only; `file://` is refused outside development),
  `OIDC_AUDIENCE`, `OIDC_ROLES_CLAIM`
- `CORS_ORIGINS` set to the frontend's public origin
- `AWS_REGION`, `BEDROCK_CHAT_MODEL_ID`, `BEDROCK_EMBEDDING_MODEL_ID`
- `DATABASE_URL` (SQLite path on EFS, or PostgreSQL later)

Do **not** set AWS access keys in the task. The task role supplies credentials.

## 5. Load balancer and health checks

- ALB target group on port 8000, health check path `/health`, expect 200.
- Frontend service on port 3000 behind a separate listener or path rule. The frontend proxies
  `/api/*` to the backend over the service-discovery name `http://backend:8000` (set `BACKEND_URL`).
- TLS terminates at the ALB. Use an ACM certificate.

## 6. SQLite to PostgreSQL

SQLite serializes writers. Several ECS tasks writing to the same file on EFS will corrupt data
or fail with lock errors. Before running more than one writer:

1. Provision RDS PostgreSQL or Aurora PostgreSQL.
2. Set `DATABASE_URL=postgresql+psycopg://...` and add `psycopg` to `backend/pyproject.toml`
   with a pinned version.
3. Run `alembic upgrade head` against the new database. The migrations use batch mode for
   SQLite; review them once against PostgreSQL.
4. Move `checkpoints.db` to the same database or keep it on EFS, but run only one ingest worker.
   LangGraph's SQLite checkpointer is not safe for concurrent writers either.

## 7. Enterprise SSO (not configured here)

The frontend's sign-in page accepts a pasted token. A production build needs the OIDC
authorization-code flow with PKCE, against the enterprise IdP. That requires:

- An OIDC client registered in the IdP, with redirect URI `https://<frontend>/auth/callback`
- Role or group claims mapped to `Learner`, `Contributor`, `Reviewer`, `Admin`
- The `OIDC_*` settings above pointed at that IdP

See the `TODO(sso)` in `frontend/lib/auth.ts`.

## 8. Verify

```bash
curl -s https://<backend-host>/health              # {"status":"ok","env":"production"}
curl -s https://<frontend-host>/api/health         # proxied through the frontend
```
