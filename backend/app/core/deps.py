import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.roles import Role
from app.core.security import decode_access_token
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentification requise ou invalide",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
        if payload.get("type") != "access":
            raise _unauthorized()
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        raise _unauthorized()

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def require_roles(*roles: Role):
    allowed = {str(r) for r in roles}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès refusé pour ce rôle")
        return user

    return checker


@dataclass(frozen=True)
class OrgScope:
    """Périmètre de données de la requête. org_id=None signifie « toutes les
    organisations » et n'est possible que pour un super_admin."""

    org_id: uuid.UUID | None


def get_org_scope(
    user: User = Depends(get_current_user),
    x_organisation_id: uuid.UUID | None = Header(default=None, alias="X-Organisation-Id"),
) -> OrgScope:
    if user.role == Role.SUPER_ADMIN:
        return OrgScope(org_id=x_organisation_id)
    if x_organisation_id is not None and x_organisation_id != user.organisation_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Organisation non autorisée")
    return OrgScope(org_id=user.organisation_id)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_write_org_id(scope: OrgScope = Depends(get_org_scope)) -> uuid.UUID:
    """Organisation cible d'une écriture. Un super_admin doit la préciser avec
    l'en-tête X-Organisation-Id ; les autres écrivent dans leur organisation."""
    if scope.org_id is None:
        raise HTTPException(
            422,
            "Précise l'organisation avec l'en-tête X-Organisation-Id",
        )
    return scope.org_id
