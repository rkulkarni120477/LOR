from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.models import LearningObject, WorkflowState
from app.storage.local import LocalStorage
from scripts import seed_demo


def test_demo_seed_is_idempotent_and_uses_review_history(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(seed_demo, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(seed_demo, "get_session_factory", lambda: sessionmaker(bind=engine))
    monkeypatch.setattr(seed_demo, "get_storage", lambda: LocalStorage(tmp_path / "files"))
    seed_demo.main()
    seed_demo.main()
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(LearningObject)) == 5
        assert (
            session.scalar(
                select(func.count())
                .select_from(LearningObject)
                .where(LearningObject.status == "published")
            )
            == 3
        )
        assert session.scalar(select(func.count()).select_from(WorkflowState)) == 10
