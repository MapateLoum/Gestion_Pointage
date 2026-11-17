from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, require_roles
from app.core.roles import Role
from app.database import get_db
from app.models import Organisation, User
from app.schemas.organisation import OrganisationCreate, OrganisationOut
from app.services import audit

router = APIRouter(prefix="/organisations", tags=["organisations"])


@router.post("", response_model=OrganisationOut, status_code=201)
def create_organisation(
    payload: OrganisationCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(Role.SUPER_ADMIN)),
):
    org = Organisation(name=payload.name, type=payload.type, country=payload.country.upper())
    db.add(org)
    db.flush()
    audit.record(
        db,
        action="organisation.created",
        actor=actor,
        organisation_id=org.id,
        object_type="organisation",
        object_id=str(org.id),
        ip=client_ip(request),
        details={"name": org.name},
    )
    db.commit()
    return org


@router.get("", response_model=list[OrganisationOut])
def list_organisations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.SUPER_ADMIN)),
):
    stmt = select(Organisation).order_by(Organisation.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())
