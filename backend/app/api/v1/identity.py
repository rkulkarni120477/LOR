"""Audited organization administration and object access controls."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS, Role, canonical
from app.core.security import Principal, require_permission
from app.db.models import (
    Department,
    Group,
    GroupMember,
    GroupRole,
    LearningObject,
    ObjectGrant,
    User,
    UserRole,
)
from app.db.models import Role as RoleRow
from app.db.session import get_db
from app.services import audit
from app.services.access import require_object

router = APIRouter(tags=["identity administration"])


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"\S")


class UserInput(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    display_name: str = Field(default="", max_length=255)
    department_id: int | None = None
    disabled: bool = False
    roles: list[str] = Field(default_factory=list, max_length=9)


class GroupInput(Named):
    department_id: int | None = None
    member_subjects: list[str] = Field(default_factory=list, max_length=500)
    roles: list[str] = Field(default_factory=list, max_length=9)


class GrantInput(BaseModel):
    grantee_type: Literal["user", "group", "department"]
    grantee_id: str = Field(min_length=1, max_length=255)
    permission: Literal["read", "edit", "review", "publish", "manage"]


class AccessInput(BaseModel):
    visibility: Literal["repository", "department", "restricted"]
    department_id: int | None = None
    grants: list[GrantInput] = Field(default_factory=list, max_length=500)


def commit(db, actor, action, kind, identity):
    audit.record(
        db, actor_subject=actor.subject, action=action, entity_type=kind, entity_id=str(identity)
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A record with this name or subject already exists") from exc


def check_department(db, identity):
    if identity is not None and db.get(Department, identity) is None:
        raise HTTPException(422, "Unknown department")


def resolve_roles(db, names):
    if any(name not in ROLE_PERMISSIONS for name in names):
        raise HTTPException(422, "Use canonical role names from /admin/roles")
    rows = []
    for name in set(names):
        row = db.scalar(select(RoleRow).where(RoleRow.name == name))
        if row is None:
            row = RoleRow(name=name)
            db.add(row)
            db.flush()
        rows.append(row)
    return rows


@router.get("/admin/roles")
def roles(actor: Principal = Depends(require_permission("organization.manage"))):
    return {
        "items": [
            {"name": name, "permissions": sorted(perms)} for name, perms in ROLE_PERMISSIONS.items()
        ]
    }


@router.get("/admin/departments")
def departments(
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
):
    return {
        "items": [
            {"id": d.id, "name": d.name}
            for d in db.scalars(select(Department).order_by(Department.name))
        ]
    }


@router.post("/admin/departments", status_code=201)
def create_department(
    body: Named,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
):
    row = Department(name=body.name.strip())
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Department already exists") from exc
    commit(db, actor, "department.create", "department", row.id)
    return {"id": row.id, "name": row.name}


@router.put("/admin/departments/{department_id}")
def edit_department(
    department_id: int,
    body: Named,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
):
    row = db.get(Department, department_id)
    if row is None:
        raise HTTPException(404, "Department not found")
    row.name = body.name.strip()
    commit(db, actor, "department.update", "department", row.id)
    return {"id": row.id, "name": row.name}


@router.get("/admin/users")
def users(
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
):
    return {
        "items": [
            {
                "id": user.id,
                "subject": user.subject,
                "display_name": user.display_name,
                "disabled": user.disabled,
                "roles_managed": user.roles_managed,
                "department_id": user.department_id,
                "roles": sorted(
                    canonical(
                        db.scalars(
                            select(RoleRow.name).join(UserRole).where(UserRole.user_id == user.id)
                        )
                    )
                ),
            }
            for user in db.scalars(select(User).order_by(User.subject).limit(1000))
        ]
    }


@router.put("/admin/users")
def save_user(
    body: UserInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("users.manage")),
):
    check_department(db, body.department_id)
    rows = resolve_roles(db, body.roles)
    if body.subject == actor.subject and (
        body.disabled or Role.SUPER_ADMIN.value not in body.roles
    ):
        raise HTTPException(409, "You cannot disable or remove your own super administrator access")
    user = db.scalar(select(User).where(User.subject == body.subject))
    if user is None:
        user = User(subject=body.subject)
        db.add(user)
        db.flush()
    user.display_name, user.department_id = body.display_name, body.department_id
    user.disabled, user.roles_managed = body.disabled, True
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add_all(UserRole(user_id=user.id, role_id=row.id) for row in rows)
    commit(db, actor, "user.access_update", "user", user.id)
    return {"saved": True, "id": user.id}


@router.get("/admin/groups")
def groups(
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
):
    return {
        "items": [
            {
                "id": g.id,
                "name": g.name,
                "department_id": g.department_id,
                "member_subjects": list(
                    db.scalars(
                        select(User.subject).join(GroupMember).where(GroupMember.group_id == g.id)
                    )
                ),
                "roles": list(
                    db.scalars(
                        select(RoleRow.name).join(GroupRole).where(GroupRole.group_id == g.id)
                    )
                ),
            }
            for g in db.scalars(select(Group).order_by(Group.name))
        ]
    }


@router.put("/admin/groups/{group_id}")
def save_group(
    group_id: int,
    body: GroupInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
):
    check_department(db, body.department_id)
    row = db.get(Group, group_id) if group_id else None
    if group_id and row is None:
        raise HTTPException(404, "Group not found")
    current = set(
        db.scalars(select(RoleRow.name).join(GroupRole).where(GroupRole.group_id == group_id))
    )
    privileged = {Role.SUPER_ADMIN.value, Role.REPOSITORY_ADMIN.value}
    if not actor.can("roles.manage") and (set(body.roles) | current) & privileged:
        raise HTTPException(403, "Only a super administrator can manage privileged groups")
    role_rows = resolve_roles(db, body.roles)
    members = list(db.scalars(select(User).where(User.subject.in_(set(body.member_subjects)))))
    if len(members) != len(set(body.member_subjects)):
        raise HTTPException(422, "Group members must be existing users")
    if row is None:
        row = Group(name=body.name.strip())
        db.add(row)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Group already exists") from exc
    row.name, row.department_id = body.name.strip(), body.department_id
    db.execute(delete(GroupMember).where(GroupMember.group_id == row.id))
    db.execute(delete(GroupRole).where(GroupRole.group_id == row.id))
    db.add_all(GroupMember(group_id=row.id, user_id=user.id) for user in members)
    db.add_all(GroupRole(group_id=row.id, role_id=role.id) for role in role_rows)
    commit(db, actor, "group.update", "group", row.id)
    return {"id": row.id, "saved": True}


@router.get("/content/{lo_id}/access")
def get_access(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
):
    require_object(db, lo_id, actor, "manage")
    lo = db.get(LearningObject, lo_id)
    return {
        "visibility": lo.visibility,
        "department_id": lo.department_id,
        "grants": [
            {"grantee_type": g.grantee_type, "grantee_id": g.grantee_id, "permission": g.permission}
            for g in db.scalars(select(ObjectGrant).where(ObjectGrant.lo_id == lo_id))
        ],
    }


@router.put("/content/{lo_id}/access")
def save_access(
    lo_id: str,
    body: AccessInput,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
):
    require_object(db, lo_id, actor, "manage")
    check_department(db, body.department_id)
    if body.visibility == "department" and body.department_id is None:
        raise HTTPException(422, "Department visibility requires a department")
    keys = set()
    for grant in body.grants:
        key = (grant.grantee_type, grant.grantee_id, grant.permission)
        if key in keys:
            raise HTTPException(422, "Duplicate grant")
        keys.add(key)
        if grant.grantee_type == "user":
            target = db.scalar(select(User.id).where(User.subject == grant.grantee_id))
        else:
            target = (
                db.get(
                    Group if grant.grantee_type == "group" else Department, int(grant.grantee_id)
                )
                if grant.grantee_id.isdecimal()
                else None
            )
        if target is None:
            raise HTTPException(422, "Grant recipient does not exist")
    lo = db.get(LearningObject, lo_id)
    lo.visibility, lo.department_id = body.visibility, body.department_id
    db.execute(delete(ObjectGrant).where(ObjectGrant.lo_id == lo_id))
    db.add_all(ObjectGrant(lo_id=lo_id, **grant.model_dump()) for grant in body.grants)
    commit(db, actor, "content.access_update", "learning_object", lo_id)
    return {"saved": True}
