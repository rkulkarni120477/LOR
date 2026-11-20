"""Collections, sharing, publishing, duplication, analytics, favorites, folders, and recent access.

Access model (one rule set everywhere):
  * The owner of a collection, or of any ancestor, controls it and its subtree.
  * A share on a collection or an ancestor grants "view" or "edit" over the subtree.
  * A published collection or ancestor is viewable by every user who may read content.
  * Items are filtered by the object read policy, so a collection never exposes an object its
    viewer cannot read.
  * Administrative actions (publish, share, move, delete) need owner access.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import (
    Collection,
    CollectionItem,
    CollectionShare,
    CollectionView,
    Department,
    Favorite,
    FavoriteCollection,
    FavoriteFolder,
    Group,
    LearningObject,
    RecentAccess,
)
from app.services import audit
from app.services.access import can_read, read_condition
from app.services.content import get_learning_object

DEFAULT_FOLDERS = ["AI in Education", "Leadership", "Product Training"]
MAX_DEPTH = 25
MAX_SUBTREE = 5000
LEVEL = {"view": 1, "edit": 2, "owner": 3}


def _now() -> datetime:
    return datetime.now(UTC)


def _grantee_clauses(actor: Principal):
    clauses = [
        and_(CollectionShare.grantee_type == "user", CollectionShare.grantee_id == actor.subject)
    ]
    if actor.group_ids:
        clauses.append(
            and_(
                CollectionShare.grantee_type == "group",
                CollectionShare.grantee_id.in_([str(g) for g in actor.group_ids]),
            )
        )
    if actor.department_ids:
        clauses.append(
            and_(
                CollectionShare.grantee_type == "department",
                CollectionShare.grantee_id.in_([str(d) for d in actor.department_ids]),
            )
        )
    return or_(*clauses)


def chain(db: Session, row: Collection) -> list[Collection]:
    """The row followed by its ancestors, nearest first."""
    result = [row]
    seen = {row.id}
    current = row
    for _ in range(MAX_DEPTH):
        if not current.parent_id:
            break
        parent = db.get(Collection, current.parent_id)
        if parent is None or parent.id in seen:
            break
        result.append(parent)
        seen.add(parent.id)
        current = parent
    return result


def access_level(db: Session, row: Collection, actor: Principal) -> str | None:
    lineage = chain(db, row)
    if actor.is_admin or any(c.owner_subject == actor.subject for c in lineage):
        return "owner"
    shares = db.scalars(
        select(CollectionShare).where(
            CollectionShare.collection_id.in_([c.id for c in lineage]),
            _grantee_clauses(actor),
        )
    ).all()
    if any(s.permission == "edit" for s in shares):
        return "edit"
    if shares:
        return "view"
    if actor.can("content.read") and any(c.visibility == "published" for c in lineage):
        return "view"
    return None


def require(db: Session, collection_id: str, actor: Principal, need: str) -> Collection:
    row = db.get(Collection, collection_id)
    if row is None:
        raise NotFoundError("collection not found")
    level = access_level(db, row, actor)
    if level is None:
        raise NotFoundError("collection not found")
    if LEVEL[level] < LEVEL[need]:
        raise HTTPException(403, f"this action needs {need} access to the collection")
    return row


def subtree_ids(db: Session, root_id: str) -> list[str]:
    ids = [root_id]
    frontier = [root_id]
    while frontier and len(ids) < MAX_SUBTREE:
        children = db.scalars(select(Collection.id).where(Collection.parent_id.in_(frontier))).all()
        frontier = [c for c in children if c not in ids]
        ids.extend(frontier)
    return ids


def accessible_ids(actor: Principal):
    """SQL subquery of every collection id the actor can view, including inherited subtrees.

    A single seed select (owned, shared, or published) feeds a recursive CTE that walks down
    to descendants, so inheritance is computed in the database rather than per row.
    """
    if actor.is_admin:
        return select(Collection.id)
    seed_conditions = [
        Collection.owner_subject == actor.subject,
        Collection.id.in_(select(CollectionShare.collection_id).where(_grantee_clauses(actor))),
    ]
    if actor.can("content.read"):
        seed_conditions.append(Collection.visibility == "published")
    seed = select(Collection.id).where(or_(*seed_conditions)).cte("accessible", recursive=True)
    child = select(Collection.id).join(seed, Collection.parent_id == seed.c.id)
    return select(seed.union(child).c.id)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes. They are stored as UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def out(
    row: Collection, *, item_count: int | None = None, level: str | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "visibility": row.visibility,
        "owner_subject": row.owner_subject,
        "parent_id": row.parent_id,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if item_count is not None:
        data["item_count"] = item_count
    if level is not None:
        data["access"] = level
    return data


def breadcrumbs(db: Session, row: Collection) -> list[dict[str, str]]:
    return [{"id": c.id, "name": c.name} for c in reversed(chain(db, row))]


def log(
    db: Session,
    actor: Principal,
    action: str,
    entity_id: str,
    details=None,
    entity_type: str = "collection",
) -> None:
    audit.record(
        db,
        actor_subject=actor.subject,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )


# --- listing and tree ------------------------------------------------------------

SORTS = {"name", "updated", "created", "items"}


def list_collections(
    db: Session,
    actor: Principal,
    *,
    parent_id: str | None,
    root_only: bool,
    sort: str,
    order: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    item_count = (
        select(func.count()).where(CollectionItem.collection_id == Collection.id).scalar_subquery()
    )
    query = select(Collection).where(Collection.id.in_(accessible_ids(actor)))
    if root_only:
        query = query.where(Collection.parent_id.is_(None))
    elif parent_id:
        query = query.where(Collection.parent_id == parent_id)
    column = {
        "name": func.lower(Collection.name),
        "updated": Collection.updated_at,
        "created": Collection.created_at,
        "items": item_count,
    }[sort]
    column = column.asc() if order == "asc" else column.desc()
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.add_columns(item_count)
        .order_by(column, Collection.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [out(row, item_count=count, level=access_level(db, row, actor)) for row, count in rows]
    return items, total


def tree(db: Session, actor: Principal) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Collection).where(Collection.id.in_(accessible_ids(actor))).limit(1000)
    ).all()
    by_id = {r.id: {**out(r), "children": []} for r in rows}
    roots = []
    for row in sorted(rows, key=lambda r: r.name.lower()):
        node = by_id[row.id]
        if row.parent_id in by_id:
            by_id[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


# --- create, update, move, publish, delete ---------------------------------------


def create(
    db: Session,
    actor: Principal,
    *,
    name: str,
    description: str,
    visibility: str,
    parent_id: str | None,
) -> Collection:
    if parent_id:
        require(db, parent_id, actor, "edit")
    row = Collection(
        id=str(uuid.uuid4()),
        name=name.strip(),
        description=description,
        owner_subject=actor.subject,
        visibility="private",
        parent_id=parent_id,
        updated_at=_now(),
    )
    db.add(row)
    if visibility == "published":
        row.visibility = "published"
        row.published_at = _now()
    log(db, actor, "collection.create", row.id, {"parent_id": parent_id})
    db.commit()
    return row


def update(
    db: Session, actor: Principal, collection_id: str, *, name: str | None, description: str | None
) -> Collection:
    row = require(db, collection_id, actor, "edit")
    if name is not None:
        row.name = name.strip()
    if description is not None:
        row.description = description
    row.updated_at = _now()
    log(db, actor, "collection.update", row.id)
    db.commit()
    return row


def move(db: Session, actor: Principal, collection_id: str, parent_id: str | None) -> Collection:
    row = require(db, collection_id, actor, "owner")
    if parent_id:
        if parent_id == collection_id:
            raise ValidationFailure("a collection cannot be its own parent")
        parent = require(db, parent_id, actor, "edit")
        if collection_id in {c.id for c in chain(db, parent)}:
            raise ValidationFailure("this move would create a cycle")
    row.parent_id = parent_id or None
    row.updated_at = _now()
    log(db, actor, "collection.move", row.id, {"parent_id": parent_id})
    db.commit()
    return row


def publish(db: Session, actor: Principal, collection_id: str, published: bool) -> Collection:
    row = require(db, collection_id, actor, "owner")
    row.visibility = "published" if published else "private"
    row.published_at = _now() if published else None
    row.updated_at = _now()
    log(db, actor, "collection.publish" if published else "collection.unpublish", row.id)
    db.commit()
    return row


def delete(db: Session, actor: Principal, collection_id: str) -> int:
    require(db, collection_id, actor, "owner")
    ids = subtree_ids(db, collection_id)
    for model, column in (
        (CollectionItem, CollectionItem.collection_id),
        (CollectionShare, CollectionShare.collection_id),
        (CollectionView, CollectionView.collection_id),
        (FavoriteCollection, FavoriteCollection.collection_id),
    ):
        for row in db.scalars(select(model).where(column.in_(ids))):
            db.delete(row)
    db.flush()
    # Deepest rows first: the database cascades parent deletes, so children must go before parents.
    by_id = {row.id: row for row in db.scalars(select(Collection).where(Collection.id.in_(ids)))}
    for cid in reversed(ids):
        if cid in by_id:
            db.delete(by_id[cid])
            db.flush()
    log(db, actor, "collection.delete", collection_id, {"removed": len(ids)})
    db.commit()
    return len(ids)


def replace_items(db: Session, actor: Principal, collection_id: str, object_ids: list[str]) -> int:
    row = require(db, collection_id, actor, "edit")
    if len(set(object_ids)) != len(object_ids):
        raise HTTPException(422, "duplicate learning objects are not allowed")
    for lo_id in object_ids:
        get_learning_object(db, lo_id, actor)  # raises when the object is not visible
    for item in db.scalars(
        select(CollectionItem).where(CollectionItem.collection_id == collection_id)
    ):
        db.delete(item)
    db.flush()
    db.add_all(
        [
            CollectionItem(collection_id=collection_id, lo_id=lo_id, position=i)
            for i, lo_id in enumerate(object_ids)
        ]
    )
    row.updated_at = _now()
    log(db, actor, "collection.reorder", collection_id, {"objects": object_ids})
    db.commit()
    return len(object_ids)


def items(db: Session, actor: Principal, collection_id: str, sort: str) -> list[LearningObject]:
    query = (
        select(LearningObject)
        .where(read_condition(actor))
        .join(CollectionItem, CollectionItem.lo_id == LearningObject.id)
        .where(CollectionItem.collection_id == collection_id)
    )
    if sort == "title":
        query = query.order_by(func.lower(LearningObject.title), LearningObject.id)
    elif sort == "updated":
        query = query.order_by(LearningObject.updated_at.desc(), LearningObject.id)
    else:
        query = query.order_by(CollectionItem.position, LearningObject.id)
    return list(db.scalars(query))


# --- sharing -----------------------------------------------------------------------


def list_shares(db: Session, actor: Principal, collection_id: str) -> list[dict[str, Any]]:
    require(db, collection_id, actor, "owner")
    rows = db.scalars(
        select(CollectionShare)
        .where(CollectionShare.collection_id == collection_id)
        .order_by(CollectionShare.grantee_type, CollectionShare.grantee_id)
    ).all()
    return [
        {"grantee_type": r.grantee_type, "grantee_id": r.grantee_id, "permission": r.permission}
        for r in rows
    ]


def share(
    db: Session,
    actor: Principal,
    collection_id: str,
    grantee_type: str,
    grantee_id: str,
    permission: str,
) -> dict[str, Any]:
    require(db, collection_id, actor, "owner")
    if grantee_type == "group" and db.get(Group, int(grantee_id)) is None:
        raise ValidationFailure("unknown group")
    if grantee_type == "department" and db.get(Department, int(grantee_id)) is None:
        raise ValidationFailure("unknown department")
    if grantee_type == "user" and grantee_id == actor.subject:
        raise ValidationFailure("you already own this collection")
    row = db.get(CollectionShare, (collection_id, grantee_type, grantee_id))
    if row is None:
        row = CollectionShare(
            collection_id=collection_id,
            grantee_type=grantee_type,
            grantee_id=grantee_id,
            permission=permission,
        )
        db.add(row)
    else:
        row.permission = permission
    log(
        db,
        actor,
        "collection.share",
        collection_id,
        {"grantee_type": grantee_type, "grantee_id": grantee_id, "permission": permission},
    )
    db.commit()
    return {"grantee_type": grantee_type, "grantee_id": grantee_id, "permission": permission}


def unshare(
    db: Session, actor: Principal, collection_id: str, grantee_type: str, grantee_id: str
) -> None:
    require(db, collection_id, actor, "owner")
    row = db.get(CollectionShare, (collection_id, grantee_type, grantee_id))
    if row is None:
        raise NotFoundError("share not found")
    db.delete(row)
    log(
        db,
        actor,
        "collection.unshare",
        collection_id,
        {"grantee_type": grantee_type, "grantee_id": grantee_id},
    )
    db.commit()


# --- duplication -------------------------------------------------------------------


def duplicate(db: Session, actor: Principal, collection_id: str) -> dict[str, Any]:
    source = require(db, collection_id, actor, "view")
    if not actor.can("collections.write"):
        raise HTTPException(403, "Requires permission: collections.write")
    copied = {"collections": 0, "items": 0, "skipped_items": 0}

    def copy_node(node: Collection, parent_id: str | None, name: str | None) -> str:
        new = Collection(
            id=str(uuid.uuid4()),
            name=(name or node.name)[:255],
            description=node.description,
            owner_subject=actor.subject,
            visibility="private",
            parent_id=parent_id,
            updated_at=_now(),
        )
        db.add(new)
        db.flush()
        copied["collections"] += 1
        position = 0
        for item in db.scalars(
            select(CollectionItem)
            .where(CollectionItem.collection_id == node.id)
            .order_by(CollectionItem.position)
        ):
            if can_read(db, item.lo_id, actor):
                db.add(CollectionItem(collection_id=new.id, lo_id=item.lo_id, position=position))
                position += 1
                copied["items"] += 1
            else:
                copied["skipped_items"] += 1
        for child in db.scalars(
            select(Collection).where(Collection.parent_id == node.id).order_by(Collection.name)
        ):
            if access_level(db, child, actor) is not None:
                copy_node(child, new.id, None)
        return new.id

    new_id = copy_node(source, None, f"Copy of {source.name}")
    log(db, actor, "collection.duplicate", new_id, {"source": collection_id, **copied})
    db.commit()
    return {"id": new_id, **copied}


# --- analytics -------------------------------------------------------------------------


def analytics(db: Session, actor: Principal, collection_id: str) -> dict[str, Any]:
    row = require(db, collection_id, actor, "edit")
    ids = subtree_ids(db, collection_id)
    since = _now() - timedelta(days=30)
    views = db.scalars(
        select(CollectionView).where(CollectionView.collection_id == collection_id)
    ).all()
    by_day = Counter(
        _aware(v.viewed_at).date().isoformat() for v in views if _aware(v.viewed_at) >= since
    )
    readable = db.execute(
        select(LearningObject.id, LearningObject.status)
        .where(read_condition(actor))
        .join(CollectionItem, CollectionItem.lo_id == LearningObject.id)
        .where(CollectionItem.collection_id.in_(ids))
        .distinct()
    ).all()
    total_items = (
        db.scalar(
            select(func.count(func.distinct(CollectionItem.lo_id))).where(
                CollectionItem.collection_id.in_(ids)
            )
        )
        or 0
    )
    return {
        "id": row.id,
        "name": row.name,
        "views": len(views),
        "unique_viewers": len({v.viewer_subject for v in views}),
        "last_viewed_at": max((v.viewed_at for v in views), default=None),
        "views_last_30_days": [{"date": day, "count": by_day[day]} for day in sorted(by_day)],
        "direct_items": db.scalar(
            select(func.count()).where(CollectionItem.collection_id == collection_id)
        )
        or 0,
        "subtree_items": total_items,
        "readable_items": len({lo_id for lo_id, _ in readable}),
        "item_status": dict(Counter(status for _, status in readable)),
        "child_collections": db.scalar(
            select(func.count()).where(Collection.parent_id == collection_id)
        )
        or 0,
        "subtree_collections": len(ids) - 1,
        "shares": db.scalar(
            select(func.count()).where(CollectionShare.collection_id == collection_id)
        )
        or 0,
        "favorited_by": db.scalar(
            select(func.count()).where(FavoriteCollection.collection_id == collection_id)
        )
        or 0,
    }


def record_view(db: Session, actor: Principal, row: Collection) -> None:
    db.add(CollectionView(collection_id=row.id, viewer_subject=actor.subject, viewed_at=_now()))
    touch(db, actor, "collection", row.id)


# --- recent access ---------------------------------------------------------------------


def touch(db: Session, actor: Principal, kind: str, target_id: str) -> None:
    row = db.get(RecentAccess, (actor.subject, kind, target_id))
    if row is None:
        db.add(
            RecentAccess(
                owner_subject=actor.subject, kind=kind, target_id=target_id, accessed_at=_now()
            )
        )
    else:
        row.accessed_at = _now()


def recent(db: Session, actor: Principal, limit: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(RecentAccess)
        .where(RecentAccess.owner_subject == actor.subject)
        .order_by(RecentAccess.accessed_at.desc())
        .limit(limit * 4)
    ).all()
    result = []
    for entry in rows:
        if len(result) >= limit:
            break
        if entry.kind == "collection":
            collection = db.get(Collection, entry.target_id)
            if collection is None or access_level(db, collection, actor) is None:
                continue
            title = collection.name
        else:
            if not can_read(db, entry.target_id, actor):
                continue
            title = db.get(LearningObject, entry.target_id).title
        result.append(
            {
                "kind": entry.kind,
                "id": entry.target_id,
                "title": title,
                "accessed_at": entry.accessed_at.isoformat(),
            }
        )
    return result


# --- favorite collections ----------------------------------------------------------------


def set_favorite_collection(db: Session, actor: Principal, collection_id: str, on: bool) -> None:
    if on:
        require(db, collection_id, actor, "view")
        if db.get(FavoriteCollection, (actor.subject, collection_id)) is None:
            db.add(
                FavoriteCollection(
                    owner_subject=actor.subject, collection_id=collection_id, created_at=_now()
                )
            )
    else:
        row = db.get(FavoriteCollection, (actor.subject, collection_id))
        if row is not None:
            db.delete(row)
    db.commit()


def favorite_collections(db: Session, actor: Principal) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(FavoriteCollection)
        .where(FavoriteCollection.owner_subject == actor.subject)
        .order_by(FavoriteCollection.created_at.desc())
    ).all()
    result = []
    for fav in rows:
        collection = db.get(Collection, fav.collection_id)
        if collection is None:
            continue
        level = access_level(db, collection, actor)
        if level is not None:
            result.append(out(collection, level=level))
    return result


# --- favorites and folders ------------------------------------------------------------------


def folder_details(db: Session, actor: Principal) -> list[dict[str, Any]]:
    counts = Counter(
        db.scalars(select(Favorite.folder).where(Favorite.owner_subject == actor.subject))
    )
    explicit = set(
        db.scalars(select(FavoriteFolder.name).where(FavoriteFolder.owner_subject == actor.subject))
    )
    names = set(DEFAULT_FOLDERS) | set(counts) | explicit
    return [
        {"name": name, "count": counts.get(name, 0), "system": name in DEFAULT_FOLDERS}
        for name in sorted(names, key=str.lower)
    ]


def _folder_exists(db: Session, actor: Principal, name: str) -> bool:
    return any(d["name"] == name for d in folder_details(db, actor))


def create_folder(db: Session, actor: Principal, name: str) -> None:
    if _folder_exists(db, actor, name):
        raise ConflictError("a folder with this name already exists")
    db.add(FavoriteFolder(owner_subject=actor.subject, name=name, created_at=_now()))
    db.commit()


def rename_folder(db: Session, actor: Principal, old: str, new: str) -> None:
    if old in DEFAULT_FOLDERS:
        raise ValidationFailure("system folders cannot be renamed")
    if not _folder_exists(db, actor, old):
        raise NotFoundError("folder not found")
    if _folder_exists(db, actor, new):
        raise ConflictError("a folder with this name already exists")
    for fav in db.scalars(
        select(Favorite).where(Favorite.owner_subject == actor.subject, Favorite.folder == old)
    ):
        fav.folder = new
    existing = db.get(FavoriteFolder, (actor.subject, old))
    if existing is not None:
        db.delete(existing)
        db.flush()
        db.add(FavoriteFolder(owner_subject=actor.subject, name=new, created_at=_now()))
    db.commit()


def delete_folder(db: Session, actor: Principal, name: str, move_to: str | None) -> int:
    if name in DEFAULT_FOLDERS:
        raise ValidationFailure("system folders cannot be deleted")
    if not _folder_exists(db, actor, name):
        raise NotFoundError("folder not found")
    target = move_to or DEFAULT_FOLDERS[0]
    if target == name:
        raise ValidationFailure("choose a different folder to move favorites into")
    if not _folder_exists(db, actor, target):
        create_folder(db, actor, target)
    moved = 0
    for fav in db.scalars(
        select(Favorite).where(Favorite.owner_subject == actor.subject, Favorite.folder == name)
    ):
        fav.folder = target
        moved += 1
    existing = db.get(FavoriteFolder, (actor.subject, name))
    if existing is not None:
        db.delete(existing)
    db.commit()
    return moved


def favorites_query(actor: Principal, folder: str | None, q: str):
    query = (
        select(LearningObject)
        .where(read_condition(actor))
        .join(Favorite, Favorite.lo_id == LearningObject.id)
        .where(Favorite.owner_subject == actor.subject)
    )
    if folder:
        query = query.where(Favorite.folder == folder)
    if q:
        query = query.where(LearningObject.title.icontains(q, autoescape=True))
    return query


def favorites_order(sort: str, order: str):
    if sort == "title":
        column = func.lower(LearningObject.title)
    else:
        column = Favorite.created_at
    column = column.asc() if order == "asc" else column.desc()
    return column, LearningObject.id
