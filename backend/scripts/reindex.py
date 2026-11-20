"""Queue all repository objects for idempotent background reindexing."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.api.deps import _default_storage  # noqa: E402
from app.db.models import LearningObject, SearchIndexJob  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.formats import extract_text  # noqa: E402
from app.services.library import _refresh_search  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extract-content", action="store_true", help="Rebuild body text for older uploads"
    )
    options = parser.parse_args()
    storage = _default_storage() if options.extract_content else None
    with get_session_factory()() as session:
        count = 0
        for lo in session.scalars(select(LearningObject)):
            if options.extract_content:
                if lo.kind != "file":
                    _refresh_search(lo)
                else:
                    version = max(lo.versions, key=lambda value: value.version_number, default=None)
                    if version and version.scan_status == "clean":
                        with storage.open(version.storage_key) as stream:
                            body = extract_text(version.original_filename, stream.read())
                        lo.search_text = lo.title + " " + body
            session.add(SearchIndexJob(lo_id=lo.id))
            count += 1
        session.commit()
    print(f"Queued {count} learning objects. Run the Celery worker and beat to process them.")


if __name__ == "__main__":
    main()
