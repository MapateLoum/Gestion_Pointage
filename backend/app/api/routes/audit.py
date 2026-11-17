from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import OrgScope, get_org_scope, require_roles
from app.core.roles import Role
from app.database import get_db
from app.models import AuditLog, User
from app.repositories.base import TenantRepository
from app.schemas.audit import AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    action: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(Role.SUPER_ADMIN, Role.ADMIN_ORGANISATION)),
):
    stmt = TenantRepository(db, AuditLog, scope.org_id).query()
    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())
