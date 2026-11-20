"""Queue all repository objects for idempotent background reindexing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.models import LearningObject, SearchIndexJob  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402


def main():
    with get_session_factory()() as session:
        count = 0
        for lo_id in session.scalars(select(LearningObject.id)):
            session.add(SearchIndexJob(lo_id=lo_id))
            count += 1
        session.commit()
    print(f"Queued {count} learning objects. Run the Celery worker and beat to process them.")


if __name__ == "__main__":
    main()
