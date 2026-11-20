"""Exercise the actual Alembic chain, rather than only ORM create_all."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core import config
from app.core.config import Settings
from app.db.session import make_engine


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
