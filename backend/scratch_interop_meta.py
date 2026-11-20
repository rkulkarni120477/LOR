import pathlib

p = pathlib.Path("app/services/interop.py")
s = p.read_text(encoding="utf-8")
old = '''    lo = content_service.ingest(
        session,
        storage,
        title=title,
        filename=package["file"],
        content_type=package.get("content_type", "application/zip"),
        data=payload,
        max_bytes=settings.max_upload_bytes,
        actor=actor,
        settings=settings,
    )
    return lo
'''
new = '''    lo = content_service.ingest(
        session,
        storage,
        title=title,
        filename=package["file"],
        content_type=package.get("content_type", "application/zip"),
        data=payload,
        max_bytes=settings.max_upload_bytes,
        actor=actor,
        settings=settings,
    )
    warnings: list[str] = []
    try:
        from app.schemas.lom import LOMMetadata
        from app.services import metadata as metadata_service

        metadata_service.update_metadata(session, lo.id, LOMMetadata.model_validate(lom), actor)
    except (DomainError, ValueError) as exc:
        # The item exists with its title. The rest of the metadata is reported, not silently dropped.
        warnings.append(str(getattr(exc, "message", exc)))
    return lo, warnings
'''
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
s = s.replace("from app.core.errors import NotFoundError, ValidationFailure", "from app.core.errors import DomainError, NotFoundError, ValidationFailure")
s = s.replace(") -> LearningObject:\n    if len(data) > MAX_BUNDLE_BYTES:", ") -> tuple[LearningObject, list[str]]:\n    if len(data) > MAX_BUNDLE_BYTES:")
p.write_text(s, encoding="utf-8")
print("import returns warnings")
