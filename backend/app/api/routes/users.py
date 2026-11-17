import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import OrgScope, client_ip, get_org_scope, require_roles
from app.core.roles import ORG_ADMIN_CREATABLE_ROLES, Role
from app.core.security import hash_password
from app.database import get_db
from app.models import Organisation, User
from app.repositories.base import TenantRepository
from app.schemas.user import UserCreate, UserOut
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])

ADMIN_ROLES = (Role.SUPER_ADMIN, Role.ADMIN_ORGANISATION)


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*ADMIN_ROLES)),
):
    if payload.role == Role.SUPER_ADMIN:
        raise HTTPException(403, "Un super_admin ne peut pas être créé via l'API")

    if actor.role == Role.ADMIN_ORGANISATION:
        if payload.role not in ORG_ADMIN_CREATABLE_ROLES:
            raise HTTPException(403, "Rôle non autorisé pour un admin d'organisation")
        if payload.organisation_id not in (None, actor.organisation_id):
            raise HTTPException(403, "Organisation non autorisée")
        org_id = actor.organisation_id
    else:
        if payload.organisation_id is None:
            raise HTTPException(422, "organisation_id est requis")
        if db.get(Organisation, payload.organisation_id) is None:
            raise HTTPException(404, "Organisation introuvable")
        org_id = payload.organisation_id

    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(409, "Cet email est déjà utilisé")

    user = User(
        organisation_id=org_id,
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=str(payload.role),
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.created",
        actor=actor,
        organisation_id=org_id,
        object_type="user",
        object_id=str(user.id),
        ip=client_ip(request),
        details={"email": email, "role": str(payload.role)},
    )
    db.commit()
    return user


@router.get("", response_model=list[UserOut])
def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*ADMIN_ROLES)),
):
    return TenantRepository(db, User, scope.org_id).list(limit, offset)


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*ADMIN_ROLES)),
):
    user = TenantRepository(db, User, scope.org_id).get(user_id)
    if user is None:
        # 404 (et pas 403) : on ne révèle pas l'existence d'un compte d'une autre organisation.
        raise HTTPException(404, "Utilisateur introuvable")
    return user
