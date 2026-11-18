"""Idempotent seed: roles and a small taxonomy. Safe to run repeatedly.

Usage (from backend/): python scripts/seed.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.security import Role  # noqa: E402
from app.db.models import Role as RoleRow  # noqa: E402
from app.db.models import TaxonomyTerm  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402

# TODO: replace with the enterprise skills taxonomy (e.g. ESCO or internal competency model).
SAMPLE_TAXONOMY = [
    ("skills", "data-literacy", "Data literacy"),
    ("skills", "cloud-security", "Cloud security"),
    ("skills", "leadership", "Leadership"),
    ("skills", "accessibility", "Accessibility"),
]


def main() -> None:
    session = get_session_factory()()
    try:
        existing_roles = set(session.scalars(select(RoleRow.name)))
        for role in Role:
            if role.value not in existing_roles:
                session.add(RoleRow(name=role.value))

        existing_terms = {(t.scheme, t.code) for t in session.scalars(select(TaxonomyTerm))}
        for scheme, code, label in SAMPLE_TAXONOMY:
            if (scheme, code) not in existing_terms:
                session.add(TaxonomyTerm(scheme=scheme, code=code, label=label))
        session.commit()
        print("seed complete")
    finally:
        session.close()


if __name__ == "__main__":
    main()
