import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import OrgScope, get_org_scope, require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.database import get_db
from app.models import AttendanceAttempt, AttendanceRecord, Person, Terminal, User
from app.schemas.kiosk import AttemptRow, RecordOut, RecordPage
from app.services import attendance

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get("", response_model=RecordPage)
def list_records(
    day: date | None = Query(None, alias="date", description="Jour (AAAA-MM-JJ) ; par défaut aujourd'hui"),
    person_id: uuid.UUID | None = None,
    kind: str | None = Query(None, pattern="^(in|out)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    start, end = attendance.local_day_bounds(settings.default_timezone, day)
    filters = [AttendanceRecord.occurred_at >= start, AttendanceRecord.occurred_at < end]
    if scope.org_id is not None:
        filters.append(AttendanceRecord.organisation_id == scope.org_id)
    if person_id:
        filters.append(AttendanceRecord.person_id == person_id)
    if kind:
        filters.append(AttendanceRecord.kind == kind)

    total = db.scalar(select(func.count(AttendanceRecord.id)).where(*filters)) or 0
    rows = db.execute(
        select(AttendanceRecord, Person.first_name, Person.last_name, Person.matricule, Terminal.name)
        .join(Person, Person.id == AttendanceRecord.person_id)
        .outerjoin(Terminal, Terminal.id == AttendanceRecord.terminal_id)
        .where(*filters)
        .order_by(AttendanceRecord.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        RecordOut(
            id=r.id, person_id=r.person_id, person_name=f"{first} {last}", matricule=matricule, kind=r.kind,
            occurred_at=r.occurred_at, terminal_name=terminal, method=r.method, face_score=r.face_score,
        )
        for r, first, last, matricule, terminal in rows
    ]
    return RecordPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/attempts", response_model=list[AttemptRow])
def list_attempts(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Toutes les tentatives, réussies ou non, avec les scores : indispensable pour régler les seuils."""
    stmt = (
        select(AttendanceAttempt, Person.first_name, Person.last_name, Terminal.name)
        .outerjoin(Person, Person.id == AttendanceAttempt.person_id)
        .outerjoin(Terminal, Terminal.id == AttendanceAttempt.terminal_id)
        .order_by(AttendanceAttempt.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if scope.org_id is not None:
        stmt = stmt.where(AttendanceAttempt.organisation_id == scope.org_id)
    if status:
        stmt = stmt.where(AttendanceAttempt.status == status)
    return [
        AttemptRow(
            id=a.id, created_at=a.created_at, terminal_name=terminal,
            person_name=f"{first} {last}" if first else None, status=a.status, reason=a.reason,
            face_score=a.face_score, face_margin=a.face_margin, details=a.details,
        )
        for a, first, last, terminal in db.execute(stmt).all()
    ]
