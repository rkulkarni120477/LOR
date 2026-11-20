"""Persisted repository organization; authorization is enforced on every read/write."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, Role, get_principal, require_roles
from app.db.models import Collection, CollectionItem, Download, Favorite, LearningObject, Version
from app.db.session import get_db
from app.schemas.content import ContentOut
from app.services import audit
from app.services.content import get_learning_object

router = APIRouter(tags=["repository"])
DEFAULT_FOLDERS = ["AI in Education", "Leadership", "Product Training"]


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"\S")
    description: str = Field(default="", max_length=5000)
    visibility: Literal["private", "public"] = "private"


class ItemInput(BaseModel):
    object_ids: list[str] = Field(max_length=500)


class FavoriteInput(BaseModel):
    folder: str = Field(default=DEFAULT_FOLDERS[0], min_length=1, max_length=255, pattern=r"\S")


def visible_objects(actor: Principal):
    query = select(LearningObject)
    if not actor.has_any({Role.CONTRIBUTOR.value, Role.REVIEWER.value}):
        query = query.where(LearningObject.status == "published")
    return query


def collection_access(db: Session, collection_id: str, actor: Principal, *, edit=False):
    row = db.get(Collection, collection_id)
    owner = row and (row.owner_subject == actor.subject or Role.ADMIN.value in actor.roles)
    if row is None or (not owner and row.visibility != "public"):
        raise NotFoundError("collection not found")
    if edit and not owner:
        raise HTTPException(403, "Only the owner or an administrator can edit this collection")
    return row


def log(db, actor, action, entity_id, entity_type="collection", details=None):
    audit.record(
        db,
        actor_subject=actor.subject,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )


def collection_out(row):
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "visibility": row.visibility,
        "owner_subject": row.owner_subject,
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    scope = visible_objects(actor).subquery()
    counts = dict(db.execute(select(scope.c.status, func.count()).group_by(scope.c.status)).all())
    # Restored versions can reference the same blob; count physical keys once.
    blobs = (
        select(Version.storage_key, func.max(Version.size_bytes).label("size"))
        .where(Version.lo_id.in_(select(scope.c.id)))
        .group_by(Version.storage_key)
        .subquery()
    )
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "storage_bytes": db.scalar(select(func.coalesce(func.sum(blobs.c.size), 0))),
        "downloads": db.scalar(
            select(func.count()).select_from(Download).where(Download.lo_id.in_(select(scope.c.id)))
        ),
        "recent": [
            ContentOut.model_validate(row)
            for row in db.scalars(
                visible_objects(actor).order_by(LearningObject.updated_at.desc()).limit(6)
            )
        ],
    }


@router.get("/collections")
def collections(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
):
    query = select(Collection)
    if Role.ADMIN.value not in actor.roles:
        query = query.where(
            or_(Collection.owner_subject == actor.subject, Collection.visibility == "public")
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Collection.created_at.desc(), Collection.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [collection_out(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/collections", status_code=201)
def create_collection(
    body: CollectionInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
):
    row = Collection(id=str(uuid.uuid4()), owner_subject=actor.subject, **body.model_dump())
    db.add(row)
    log(db, actor, "collection.create", row.id)
    db.commit()
    return collection_out(row)


@router.get("/collections/{collection_id}")
def get_collection(
    collection_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
):
    row = collection_access(db, collection_id, actor)
    items = db.scalars(
        visible_objects(actor)
        .join(CollectionItem)
        .where(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.position)
    )
    return {**collection_out(row), "items": [ContentOut.model_validate(item) for item in items]}


@router.put("/collections/{collection_id}")
def edit_collection(
    collection_id: str,
    body: CollectionInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
):
    row = collection_access(db, collection_id, actor, edit=True)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    log(db, actor, "collection.update", row.id)
    db.commit()
    return collection_out(row)


@router.put("/collections/{collection_id}/items")
def replace_items(
    collection_id: str,
    body: ItemInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
):
    collection_access(db, collection_id, actor, edit=True)
    if len(set(body.object_ids)) != len(body.object_ids):
        raise HTTPException(422, "Duplicate learning objects are not allowed")
    for lo_id in body.object_ids:
        get_learning_object(db, lo_id, actor)
    for item in db.scalars(
        select(CollectionItem).where(CollectionItem.collection_id == collection_id)
    ):
        db.delete(item)
    db.flush()
    db.add_all(
        [
            CollectionItem(collection_id=collection_id, lo_id=lo_id, position=index)
            for index, lo_id in enumerate(body.object_ids)
        ]
    )
    log(db, actor, "collection.reorder", collection_id, details={"objects": body.object_ids})
    db.commit()
    return {"saved": len(body.object_ids)}


@router.delete("/collections/{collection_id}")
def delete_collection(
    collection_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
):
    row = collection_access(db, collection_id, actor, edit=True)
    db.delete(row)
    log(db, actor, "collection.delete", collection_id)
    db.commit()
    return {"deleted": True}


@router.get("/favorites/folders")
def favorite_folders(db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    custom = db.scalars(
        select(Favorite.folder).where(Favorite.owner_subject == actor.subject).distinct()
    ).all()
    return {"items": list(dict.fromkeys(DEFAULT_FOLDERS + sorted(custom)))}


@router.get("/favorites")
def favorites(
    folder: str | None = Query(None, max_length=255),
    q: str = Query("", max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
):
    query = visible_objects(actor).join(Favorite).where(Favorite.owner_subject == actor.subject)
    if folder:
        query = query.where(Favorite.folder == folder)
    if q:
        query = query.where(LearningObject.title.icontains(q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Favorite.created_at.desc(), LearningObject.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [ContentOut.model_validate(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put("/favorites/{lo_id}")
def save_favorite(
    lo_id: str,
    body: FavoriteInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
):
    get_learning_object(db, lo_id, actor)
    row = db.get(Favorite, (actor.subject, lo_id))
    if row:
        row.folder = body.folder
    else:
        db.add(Favorite(owner_subject=actor.subject, lo_id=lo_id, folder=body.folder))
    log(db, actor, "favorite.save", lo_id, "learning_object", {"folder": body.folder})
    db.commit()
    return {"saved": True}


@router.delete("/favorites/{lo_id}")
def remove_favorite(
    lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
):
    row = db.get(Favorite, (actor.subject, lo_id))
    if row:
        db.delete(row)
        log(db, actor, "favorite.remove", lo_id, "learning_object")
        db.commit()
    return {"deleted": True}
