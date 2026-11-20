"""Development-only sample courses; run after migrations and seed.py.

Uses real repository services and workflow audit records. Idempotent by sample title/author.
"""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.api.deps import get_storage  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import Principal  # noqa: E402
from app.db.models import LearningObject  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.schemas.lom import LOMMetadata  # noqa: E402
from app.services import content, metadata, workflow  # noqa: E402

COURSES = [
    (
        "Responsible AI in Education",
        "AI in Education",
        "Evaluate AI-generated learning materials, protect learner data, and review bias.",
        "published",
    ),
    (
        "Coaching for New Managers",
        "Leadership",
        "Practice feedback conversations and build a clear development plan.",
        "published",
    ),
    (
        "Product Discovery Essentials",
        "Product Training",
        "Interview users, frame hypotheses, and prioritize learning experiments.",
        "published",
    ),
    (
        "Accessible Learning Design",
        "Accessibility",
        "Design keyboard-friendly learning activities with meaningful alternatives.",
        "submitted",
    ),
    (
        "Cloud Security Foundations",
        "Cloud Security",
        "Apply least privilege and protect content throughout its lifecycle.",
        "draft",
    ),
]


def main():
    settings = get_settings()
    if settings.env != "development":
        raise SystemExit("Demo seeding requires ENV=development")
    actor = Principal(subject="dev-contributor", roles=frozenset({"Contributor"}))
    reviewer = Principal(subject="dev-reviewer", roles=frozenset({"Reviewer"}))
    with get_session_factory()() as session:
        for title, subject, description, target in COURSES:
            if session.scalar(
                select(LearningObject.id).where(
                    LearningObject.title == title, LearningObject.created_by == actor.subject
                )
            ):
                continue
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(
                    "index.html",
                    f"<!doctype html><html lang='en'><title>{title}</title>"
                    f"<body><h1>{title}</h1><p>{description}</p><h2>Reflection</h2>"
                    "<p>How will you apply this in your work?</p></body></html>",
                )
                archive.writestr("LICENSE.txt", "CC-BY-4.0; ELOR demonstration content")
            lo = content.create_learning_object(
                session,
                get_storage(),
                title=title,
                filename="course.zip",
                content_type="application/zip",
                data=buffer.getvalue(),
                max_bytes=settings.max_upload_bytes,
                actor=actor,
            )
            metadata.update_metadata(
                session,
                lo.id,
                LOMMetadata(
                    title=title,
                    subject=subject,
                    description=description,
                    language="en",
                    keywords=[subject, "demonstration"],
                    license="CC-BY-4.0",
                    learning_resource_type="course",
                    duration="PT15M",
                ),
                actor,
            )
            if target in {"submitted", "published"}:
                workflow.submit(session, lo.id, actor, "Demo content ready for review")
            if target == "published":
                workflow.decide(session, lo.id, reviewer, "approve", "Demo reviewed")
                workflow.publish(session, lo.id, reviewer)
    print("Demo courses ready: 3 published, 1 submitted, 1 draft (existing samples retained).")


if __name__ == "__main__":
    main()
