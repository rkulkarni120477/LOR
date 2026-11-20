import pathlib


def edit(path, pairs):
    p = pathlib.Path(path)
    s = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:70], s.count(old))
        s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")


# Dead branch removal in versioning.restore.
edit("app/services/versioning.py", [(
    '''    if target_version is not None and target_version not in current_numbers:
        pass  # the file version no longer exists; the snapshot still restores metadata
    current_top''',
    '''    current_top''',
)])

# 1. Metadata saves.
edit("app/services/metadata.py", [(
    '''    meta.updated_by = actor.subject
    meta.updated_at = datetime.now(UTC)
    lo.title = data["title"]
''',
    '''    meta.updated_by = actor.subject
    meta.updated_at = datetime.now(UTC)
    lo.title = data["title"]
    versioning.ensure_snapshot(session, lo, actor, "metadata")
''',
), (
    "from app.services import taxonomy\n",
    "from app.services import taxonomy, versioning\n",
)])

# 2. Library drafts and creation.
edit("app/services/library.py", [(
    '''def create_rich_text(session: Session, actor: Principal, data: RichTextIn) -> LearningObject:
    lo = _new_authored(''',
    '''def create_rich_text(session: Session, actor: Principal, data: RichTextIn) -> LearningObject:
    lo = _new_authored(''',
)])
s = pathlib.Path("app/services/library.py").read_text(encoding="utf-8")
s = s.replace('''    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.create",
        entity_id=lo.id,
        details={"kind": "rich_text"},
    )
    _commit(session, lo)''', '''    versioning.ensure_snapshot(session, lo, actor, "create")
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.create",
        entity_id=lo.id,
        details={"kind": "rich_text"},
    )
    _commit(session, lo)''')
s = s.replace('''    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.create",
        entity_id=lo.id,
        details={"kind": data.kind},
    )
    _commit(session, lo)''', '''    versioning.ensure_snapshot(session, lo, actor, "create")
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.create",
        entity_id=lo.id,
        details={"kind": data.kind},
    )
    _commit(session, lo)''')
s = s.replace('''    _sync_metadata(session, lo, **current, actor=actor.subject)
    _refresh_search(lo)
    lo.revision += 1''', '''    _sync_metadata(session, lo, **current, actor=actor.subject)
    _refresh_search(lo)
    lo.revision += 1
    versioning.ensure_snapshot(session, lo, actor, "metadata")''')
s = s.replace("from app.services.users import ensure_user\n", "from app.services import versioning\nfrom app.services.users import ensure_user\n", 1)
pathlib.Path("app/services/library.py").write_text(s, encoding="utf-8")
print("library hooks:", s.count("ensure_snapshot"))

# 3. Package ingest (new learning objects).
edit("app/services/content.py", [(
    '''    package_meta = dict(report.metadata)
    package_meta["size_bytes"] = len(data)
    lo = _new_learning_object(session, lo_id, title, actor, STATUS_DRAFT)
    lo.versions.append(
        _version(
            safe_name,
            storage_key,
            content_type,
            data,
            sha,
            actor,
            "clean",
            report.to_json(),
            package_meta,
            thumb_key,
        )
    )''',
    '''    package_meta = dict(report.metadata)
    package_meta["size_bytes"] = len(data)
    lo = _new_learning_object(session, lo_id, title, actor, STATUS_DRAFT)
    lo.versions.append(
        _version(
            safe_name,
            storage_key,
            content_type,
            data,
            sha,
            actor,
            "clean",
            report.to_json(),
            package_meta,
            thumb_key,
        )
    )
    versioning.ensure_snapshot(session, lo, actor, "create")''',
)])
s = pathlib.Path("app/services/content.py").read_text(encoding="utf-8")
s = s.replace("from app.services import audit\n", "from app.services import audit\nfrom app.services import versioning\n", 1)
pathlib.Path("app/services/content.py").write_text(s, encoding="utf-8")

# 4. File restore keeps its behavior and now records a snapshot.
edit("app/api/v1/content.py", [(
    '''    lo.status = "draft"
    db.add(
        WorkflowState(
            lo_id=lo_id,
            from_state=previous_status,
            to_state="draft",
            actor_subject=principal.subject,
            comment=f"Restored file version {version_number} as {new_number}",
        )
    )''',
    '''    lo.status = "draft"
    db.add(
        WorkflowState(
            lo_id=lo_id,
            from_state=previous_status,
            to_state="draft",
            actor_subject=principal.subject,
            comment=f"Restored file version {version_number} as {new_number}",
        )
    )
    versioning.ensure_snapshot(db, lo, principal, "file", f"Restored file version {version_number}")''',
), (
    "from app.services import collections as collection_service\n",
    "from app.services import collections as collection_service\nfrom app.services import versioning\n",
)])

# 5. Submission binds the review to the current snapshot; publishing checks the binding.
edit("app/services/workflow.py", [(
    '''    resolved_id, policy_name, stages = resolve_policy(session, policy_id)
    transition(session, lo, SUBMITTED, actor, comment, commit=False)''',
    '''    resolved_id, policy_name, stages = resolve_policy(session, policy_id)
    snapshot = versioning.ensure_snapshot(session, lo, actor, "submit")
    transition(session, lo, SUBMITTED, actor, comment, commit=False)''',
), (
    '''        submitted_by=actor.subject,
    )
    session.add(case)
    session.flush()
    _open_stage(session, case, lo)''',
    '''        submitted_by=actor.subject,
        snapshot_id=snapshot.id,
    )
    session.add(case)
    session.flush()
    _open_stage(session, case, lo)''',
), (
    '''    last = latest_case(session, lo_id)
    if last is not None and last.status == "approved" and not _is_super(actor):''',
    '''    last = latest_case(session, lo_id)
    if last is not None and last.status == "approved":
        current = versioning.latest(session, lo_id)
        if current is not None and last.snapshot_id != current.id:
            raise ConflictError("the item changed after it was approved; resubmit for approval")
    if last is not None and last.status == "approved" and not _is_super(actor):''',
), (
    "from app.core.errors import (\n    InvalidTransitionError,",
    "from app.core.errors import (\n    ConflictError,\n    InvalidTransitionError,",
), (
    "from app.services import notifications as notify_service\n",
    "from app.services import notifications as notify_service\nfrom app.services import versioning\n",
)])
print("hooks installed")
