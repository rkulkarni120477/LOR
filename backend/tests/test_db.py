"""Phase 2: models, relationships, and indexes."""

from sqlalchemy import inspect, select

from app.db.models import LearningObject, MetadataLOM, Version


def test_fixture_inserts_learning_object_with_version_and_metadata(db_session, seeded_lo):
    lo = db_session.get(LearningObject, seeded_lo)
    assert lo is not None
    assert lo.status == "draft"
    assert len(lo.versions) == 1
    assert lo.versions[0].version_number == 1
    assert lo.metadata_record is not None
    assert lo.metadata_record.title == "Intro to Data"


def test_metadata_is_linked_by_foreign_key(db_session, seeded_lo):
    meta = db_session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == seeded_lo))
    assert meta is not None
    assert meta.learning_object.id == seeded_lo


def test_required_indexes_exist(engine):
    inspector = inspect(engine)
    lo_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("learning_objects")}
    meta_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("metadata_lom")}
    xapi_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("xapi_statements")}
    assert ("status",) in lo_indexes
    assert ("lo_id",) in meta_indexes
    assert ("actor_id",) in xapi_indexes


def test_version_numbers_are_unique_per_object(db_session, seeded_lo):
    from sqlalchemy.exc import IntegrityError

    db_session.add(
        Version(
            lo_id=seeded_lo,
            version_number=1,
            storage_key="dup",
            original_filename="dup.zip",
            content_type="application/zip",
            size_bytes=1,
            sha256="0" * 64,
            created_by="x",
        )
    )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:  # pragma: no cover - the constraint must fire
        raise AssertionError("duplicate version_number was accepted")
