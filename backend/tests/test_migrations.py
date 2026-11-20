"""Exercise the actual Alembic chain, rather than only ORM create_all."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core import config
from app.core.config import Settings
from app.db.session import make_engine
from sqlalchemy import text


def test_migrations_upgrade_downgrade_and_schema(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setattr(config, "get_settings", lambda: Settings(_env_file=None, database_url=url))
    root = Path(__file__).resolve().parents[1]
    alembic = Config(str(root / "alembic.ini"))
    alembic.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(alembic, "head")


    engine = make_engine(url)
    inspector = inspect(engine)
    assert {"collections", "collection_items", "favorites", "downloads"} <= set(
        inspector.get_table_names()
    )
    assert inspector.get_pk_constraint("favorites")["constrained_columns"] == [
        "owner_subject",
        "lo_id",
    ]
    assert inspector.get_foreign_keys("collection_items")[0]["options"]["ondelete"] == "CASCADE"
    engine.dispose()
    command.downgrade(alembic, "851cd3b1621c")
    command.upgrade(alembic, "head")


def test_identity_upgrade_preserves_existing_content_versions(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'existing.db').as_posix()}"
    monkeypatch.setattr(config, "get_settings", lambda: Settings(_env_file=None, database_url=url))
    root = Path(__file__).resolve().parents[1]
    migration = Config(str(root / "alembic.ini"))
    migration.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(migration, "b23c45d67e89")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO learning_objects (id,title,status,created_by,created_at,updated_at) VALUES ('existing','Course','draft','author',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO versions (lo_id,version_number,storage_key,original_filename,content_type,size_bytes,sha256,created_by,created_at) VALUES ('existing',1,'course.pdf','course.pdf','application/pdf',4,'hash','author',CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(migration, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM versions WHERE lo_id='existing'")) == 1
        assert (
            connection.scalar(text("SELECT visibility FROM learning_objects WHERE id='existing'"))
            == "repository"
        )
    engine.dispose()
