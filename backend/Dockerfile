# Backend image. Pinned base; dependencies installed from pyproject.toml.
FROM python:3.12.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend

COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade "pip==25.2" && pip install .

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# Data directories are volumes in docker-compose (lor.db, checkpoints.db, storage).
RUN mkdir -p /srv/data && useradd --create-home app && chown -R app /srv/data /srv/backend
USER app
ENV DATABASE_URL=sqlite:////srv/data/lor.db \
    CHECKPOINT_DB_PATH=/srv/data/checkpoints.db \
    VECTOR_DB_PATH=/srv/data/vectors.db \
    LOCAL_STORAGE_PATH=/srv/data/storage

EXPOSE 8000
# Migrations run at container start so the schema is current before serving.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
