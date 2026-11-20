"""Collections, sharing, publishing, duplication, analytics, favorites, folders, recent access.
Authorization lives in app.services.collections; these handlers only parse and delegate."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import Principal, get_principal
from app.db.models import Collection, Favorite
from app.db.session import get_db
from app.schemas.content import ContentOut
from app.services import collections as service
from app.services.content import get_learning_object

router = APIRouter(tags=["collections and favorites"])
NAME = Field(min_length=1, max_length=255, pattern=r"\S")


class CollectionInput(BaseModel):
    name: str = NAME
    description: str = Field(default="", max_length=5000)
    visibility: Literal["private", "published"] = "private"
    parent_id: str | None = Field(default=None, max_length=36)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255, pattern=r"\S")
    description: str | None = Field(default=None, max_length=5000)
    # Changing visibility publishes or unpublishes, which only the owner may do.
    visibility: Literal["private", "published"] | None = None


class MoveInput(BaseModel):
    parent_id: str | None = Field(default=None, max_length=36)


class PublishInput(BaseModel):
    published: bool


class ItemInput(BaseModel):
    object_ids: list[str] = Field(max_length=500)


class ShareInput(BaseModel):
    grantee_type: Literal["user", "group", "department"]
    grantee_id: str = Field(min_length=1, max_length=255)
    permission: Literal["view", "edit"] = "view"


class FavoriteInput(BaseModel):
    folder: str = Field(
        default=service.DEFAULT_FOLDERS[0], min_length=1, max_length=255, pattern=r"\S"
    )


class FolderInput(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]*\S[^/\\]*$")


def _require_write(actor: Principal) -> None:
    if not actor.can("collections.write"):
        raise HTTPException(403, "Requires permission: collections.write")


# --- collections ----------------------------------------------------------------------


@router.get("/collections")
def list_collections(
    parent: str | None = Query(None, max_length=36, description='a collection id, or "root"'),
    sort: Literal["name", "updated", "created", "items"] = "name",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    items, total = service.list_collections(
        db,
        actor,
        parent_id=None if parent in (None, "root") else parent,
        root_only=parent == "root",
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/collections/tree")
def collection_tree(
    db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    return {"items": service.tree(db, actor)}


@router.post("/collections", status_code=201)
def create_collection(
    body: CollectionInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    row = service.create(
        db,
        actor,
        name=body.name,
        description=body.description,
        visibility=body.visibility,
        parent_id=body.parent_id,
    )
    return service.out(row, item_count=0, level="owner")


@router.get("/collections/{collection_id}")
def get_collection(
    collection_id: str,
    sort: Literal["position", "title", "updated"] = "position",
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    row = service.require(db, collection_id, actor, "view")
    service.record_view(db, actor, row)
    db.commit()
    objects = service.items(db, actor, collection_id, sort)
    children = db.scalars(
        select(Collection).where(Collection.parent_id == row.id).order_by(Collection.name)
    ).all()
    return {
        **service.out(row, item_count=len(objects), level=service.access_level(db, row, actor)),
        "breadcrumbs": service.breadcrumbs(db, row),
        "children": [{"id": c.id, "name": c.name, "visibility": c.visibility} for c in children],
        "items": [ContentOut.model_validate(item) for item in objects],
    }


@router.put("/collections/{collection_id}")
def edit_collection(
    collection_id: str,
    body: CollectionUpdate,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    if body.name is not None or body.description is not None:
        service.update(db, actor, collection_id, name=body.name, description=body.description)
    if body.visibility is not None:
        service.publish(db, actor, collection_id, body.visibility == "published")
    row = service.require(db, collection_id, actor, "view")
    return service.out(row, level=service.access_level(db, row, actor))


@router.put("/collections/{collection_id}/move")
def move_collection(
    collection_id: str,
    body: MoveInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    return service.out(service.move(db, actor, collection_id, body.parent_id))


@router.put("/collections/{collection_id}/publish")
def publish_collection(
    collection_id: str,
    body: PublishInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    return service.out(service.publish(db, actor, collection_id, body.published))


@router.put("/collections/{collection_id}/items")
def replace_items(
    collection_id: str,
    body: ItemInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    return {"saved": service.replace_items(db, actor, collection_id, body.object_ids)}


@router.delete("/collections/{collection_id}")
def delete_collection(
    collection_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    return {"deleted": True, "removed": service.delete(db, actor, collection_id)}


@router.post("/collections/{collection_id}/duplicate", status_code=201)
def duplicate_collection(
    collection_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return service.duplicate(db, actor, collection_id)


@router.get("/collections/{collection_id}/analytics")
def collection_analytics(
    collection_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return service.analytics(db, actor, collection_id)


@router.get("/collections/{collection_id}/shares")
def list_shares(
    collection_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    return {"items": service.list_shares(db, actor, collection_id)}


@router.put("/collections/{collection_id}/shares")
def share_collection(
    collection_id: str,
    body: ShareInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    _require_write(actor)
    return service.share(
        db, actor, collection_id, body.grantee_type, body.grantee_id, body.permission
    )


@router.delete("/collections/{collection_id}/shares/{grantee_type}/{grantee_id}")
def unshare_collection(
    collection_id: str,
    grantee_type: Literal["user", "group", "department"],
    grantee_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    service.unshare(db, actor, collection_id, grantee_type, grantee_id)
    return {"deleted": True}


# --- favorite collections -------------------------------------------------------------


@router.put("/favorites/collections/{collection_id}")
def favorite_collection(
    collection_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    service.set_favorite_collection(db, actor, collection_id, True)
    return {"favorite": True}


@router.delete("/favorites/collections/{collection_id}")
def unfavorite_collection(
    collection_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    service.set_favorite_collection(db, actor, collection_id, False)
    return {"favorite": False}


@router.get("/favorites/collections")
def favorite_collections(
    db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    return {"items": service.favorite_collections(db, actor)}


# --- favorite objects and folders -------------------------------------------------------


@router.get("/favorites/folders")
def favorite_folders(
    db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    details = service.folder_details(db, actor)
    return {"items": [d["name"] for d in details], "details": details}


@router.post("/favorites/folders", status_code=201)
def create_folder(
    body: FolderInput, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    service.create_folder(db, actor, body.name.strip())
    return {"name": body.name.strip()}


@router.put("/favorites/folders/{name}")
def rename_folder(
    name: str,
    body: FolderInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    service.rename_folder(db, actor, name, body.name.strip())
    return {"name": body.name.strip()}


@router.delete("/favorites/folders/{name}")
def delete_folder(
    name: str,
    move_to: str | None = Query(None, max_length=255),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return {"moved": service.delete_folder(db, actor, name, move_to)}


@router.get("/favorites")
def favorites(
    folder: str | None = Query(None, max_length=255),
    q: str = Query("", max_length=255),
    sort: Literal["added", "title"] = "added",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    query = service.favorites_query(actor, folder, q)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    primary, tiebreak = service.favorites_order(sort, order)
    rows = db.execute(
        query.add_columns(Favorite.folder)
        .order_by(primary, tiebreak)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {**ContentOut.model_validate(obj).model_dump(mode="json"), "folder": folder}
            for obj, folder in rows
        ],
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
) -> dict[str, Any]:
    if not actor.can("favorites.write"):
        raise HTTPException(403, "Requires permission: favorites.write")
    get_learning_object(db, lo_id, actor)
    row = db.get(Favorite, (actor.subject, lo_id))
    if row:
        row.folder = body.folder
    else:
        db.add(Favorite(owner_subject=actor.subject, lo_id=lo_id, folder=body.folder))
    service.log(
        db, actor, "favorite.save", lo_id, {"folder": body.folder}, entity_type="learning_object"
    )
    db.commit()
    return {"saved": True}


@router.delete("/favorites/{lo_id}")
def remove_favorite(
    lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    if not actor.can("favorites.write"):
        raise HTTPException(403, "Requires permission: favorites.write")
    row = db.get(Favorite, (actor.subject, lo_id))
    if row:
        db.delete(row)
        service.log(db, actor, "favorite.remove", lo_id, entity_type="learning_object")
        db.commit()
    return {"deleted": True}


# --- recent access ----------------------------------------------------------------------


@router.get("/recent")
def recent(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return {"items": service.recent(db, actor, limit)}
