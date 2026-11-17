"""Sites, départements et groupes : trois ressources très proches, générées par la
même fonction pour éviter de dupliquer la logique (isolation par organisation,
droits, audit, unicité du nom)."""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db_utils import commit_or_conflict
from app.core.deps import OrgScope, client_ip, get_org_scope, get_write_org_id, require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.database import get_db
from app.models import Department, Group, Site, User
from app.repositories.base import TenantRepository
from app.schemas.structure import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)
from app.services import audit

NOT_NULL_ON_UPDATE = {"name", "kind", "timezone", "is_active"}


def build_crud_router(
    *,
    prefix: str,
    tag: str,
    label: str,
    model: Any,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    out_schema: type[BaseModel],
    refs: dict[str, Any] | None = None,
) -> APIRouter:
    refs = refs or {}
    router = APIRouter(prefix=prefix, tags=[tag])

    def check_refs(db: Session, org_id: uuid.UUID, data: dict) -> None:
        """Un site / département référencé doit appartenir à la MÊME organisation."""
        for field, ref_model in refs.items():
            ref_id = data.get(field)
            if ref_id is not None and TenantRepository(db, ref_model, org_id).get(ref_id) is None:
                raise HTTPException(422, f"{field} invalide pour cette organisation")

    def name_taken(db: Session, org_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(model.id).where(model.organisation_id == org_id, model.name == name)
        if exclude is not None:
            stmt = stmt.where(model.id != exclude)
        return db.scalar(stmt) is not None

    @router.get("", response_model=list[out_schema])
    def list_items(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        scope: OrgScope = Depends(get_org_scope),
        _: User = Depends(require_roles(*READ_ROLES)),
    ):
        stmt = TenantRepository(db, model, scope.org_id).query()
        return list(db.scalars(stmt.order_by(model.name).limit(limit).offset(offset)).all())

    @router.post("", response_model=out_schema, status_code=201)
    def create_item(
        payload: create_schema,  # type: ignore[valid-type]
        request: Request,
        db: Session = Depends(get_db),
        actor: User = Depends(require_roles(*WRITE_ROLES)),
        org_id: uuid.UUID = Depends(get_write_org_id),
    ):
        data = payload.model_dump()
        data["name"] = data["name"].strip()
        check_refs(db, org_id, data)
        if name_taken(db, org_id, data["name"]):
            raise HTTPException(409, f"Ce nom de {label} existe déjà")
        obj = model(organisation_id=org_id, **data)
        db.add(obj)
        db.flush()
        audit.record(
            db,
            action=f"{tag}.created",
            actor=actor,
            organisation_id=org_id,
            object_type=tag,
            object_id=str(obj.id),
            ip=client_ip(request),
            details={"name": obj.name},
        )
        commit_or_conflict(db, f"Ce nom de {label} existe déjà")
        return obj

    @router.get("/{item_id}", response_model=out_schema)
    def get_item(
        item_id: uuid.UUID,
        db: Session = Depends(get_db),
        scope: OrgScope = Depends(get_org_scope),
        _: User = Depends(require_roles(*READ_ROLES)),
    ):
        obj = TenantRepository(db, model, scope.org_id).get(item_id)
        if obj is None:
            raise HTTPException(404, f"{label.capitalize()} introuvable")
        return obj

    @router.patch("/{item_id}", response_model=out_schema)
    def update_item(
        item_id: uuid.UUID,
        payload: update_schema,  # type: ignore[valid-type]
        request: Request,
        db: Session = Depends(get_db),
        actor: User = Depends(require_roles(*WRITE_ROLES)),
        org_id: uuid.UUID = Depends(get_write_org_id),
    ):
        obj = TenantRepository(db, model, org_id).get(item_id)
        if obj is None:
            raise HTTPException(404, f"{label.capitalize()} introuvable")
        data = payload.model_dump(exclude_unset=True)
        for field in NOT_NULL_ON_UPDATE & data.keys():
            if data[field] is None:
                raise HTTPException(422, f"{field} ne peut pas être vide")
        if "name" in data:
            data["name"] = data["name"].strip()
            if name_taken(db, org_id, data["name"], exclude=obj.id):
                raise HTTPException(409, f"Ce nom de {label} existe déjà")
        check_refs(db, org_id, data)
        for field, value in data.items():
            setattr(obj, field, value)
        audit.record(
            db,
            action=f"{tag}.updated",
            actor=actor,
            organisation_id=org_id,
            object_type=tag,
            object_id=str(obj.id),
            ip=client_ip(request),
            details={"fields": sorted(data.keys())},
        )
        commit_or_conflict(db, f"Ce nom de {label} existe déjà")
        return obj

    @router.delete("/{item_id}", status_code=204)
    def delete_item(
        item_id: uuid.UUID,
        request: Request,
        db: Session = Depends(get_db),
        actor: User = Depends(require_roles(*WRITE_ROLES)),
        org_id: uuid.UUID = Depends(get_write_org_id),
    ):
        obj = TenantRepository(db, model, org_id).get(item_id)
        if obj is None:
            raise HTTPException(404, f"{label.capitalize()} introuvable")
        name = obj.name
        db.delete(obj)
        audit.record(
            db,
            action=f"{tag}.deleted",
            actor=actor,
            organisation_id=org_id,
            object_type=tag,
            object_id=str(item_id),
            ip=client_ip(request),
            details={"name": name},
        )
        db.commit()
        return Response(status_code=204)

    return router


sites_router = build_crud_router(
    prefix="/sites", tag="site", label="site", model=Site,
    create_schema=SiteCreate, update_schema=SiteUpdate, out_schema=SiteOut,
)
departments_router = build_crud_router(
    prefix="/departments", tag="department", label="département", model=Department,
    create_schema=DepartmentCreate, update_schema=DepartmentUpdate, out_schema=DepartmentOut,
    refs={"site_id": Site},
)
groups_router = build_crud_router(
    prefix="/groups", tag="group", label="groupe", model=Group,
    create_schema=GroupCreate, update_schema=GroupUpdate, out_schema=GroupOut,
    refs={"site_id": Site, "department_id": Department},
)
