import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db_utils import commit_or_conflict
from app.core.deps import OrgScope, client_ip, get_org_scope, get_write_org_id, hash_terminal_key, require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.database import get_db
from app.models import Site, Terminal, User
from app.repositories.base import TenantRepository
from app.schemas.kiosk import TerminalCreate, TerminalCreated, TerminalOut, TerminalUpdate
from app.services import audit

router = APIRouter(prefix="/terminals", tags=["terminals"])


def _new_key() -> str:
    return "trm_" + secrets.token_urlsafe(32)


def _check_site(db: Session, org_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    if site_id is not None and TenantRepository(db, Site, org_id).get(site_id) is None:
        raise HTTPException(422, "site_id invalide pour cette organisation")


def _name_taken(db: Session, org_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Terminal.id).where(Terminal.organisation_id == org_id, Terminal.name == name)
    if exclude:
        stmt = stmt.where(Terminal.id != exclude)
    return db.scalar(stmt) is not None


@router.get("", response_model=list[TerminalOut])
def list_terminals(
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    stmt = TenantRepository(db, Terminal, scope.org_id).query().order_by(Terminal.name)
    return list(db.scalars(stmt).all())


@router.post("", response_model=TerminalCreated, status_code=201)
def create_terminal(
    payload: TerminalCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    name = payload.name.strip()
    _check_site(db, org_id, payload.site_id)
    if _name_taken(db, org_id, name):
        raise HTTPException(409, "Ce nom de terminal existe déjà")
    key = _new_key()
    terminal = Terminal(
        organisation_id=org_id, site_id=payload.site_id, name=name, key_hash=hash_terminal_key(key),
        key_prefix=key[:8], fingerprint_required=payload.fingerprint_required,
    )
    db.add(terminal)
    db.flush()
    audit.record(
        db, action="terminal.created", actor=actor, organisation_id=org_id, object_type="terminal",
        object_id=str(terminal.id), ip=client_ip(request), details={"name": name},
    )
    commit_or_conflict(db, "Ce nom de terminal existe déjà")
    return TerminalCreated.model_validate({**TerminalOut.model_validate(terminal).model_dump(), "key": key})


@router.patch("/{terminal_id}", response_model=TerminalOut)
def update_terminal(
    terminal_id: uuid.UUID,
    payload: TerminalUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    terminal = TenantRepository(db, Terminal, org_id).get(terminal_id)
    if terminal is None:
        raise HTTPException(404, "Terminal introuvable")
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "fingerprint_required", "is_active"):
        if field in data and data[field] is None:
            raise HTTPException(422, f"{field} ne peut pas être vide")
    if "name" in data:
        data["name"] = data["name"].strip()
        if _name_taken(db, org_id, data["name"], exclude=terminal.id):
            raise HTTPException(409, "Ce nom de terminal existe déjà")
    if "site_id" in data:
        _check_site(db, org_id, data["site_id"])
    for field, value in data.items():
        setattr(terminal, field, value)
    audit.record(
        db, action="terminal.updated", actor=actor, organisation_id=org_id, object_type="terminal",
        object_id=str(terminal.id), ip=client_ip(request), details={"fields": sorted(data.keys())},
    )
    commit_or_conflict(db, "Ce nom de terminal existe déjà")
    return terminal


@router.post("/{terminal_id}/rotate-key", response_model=TerminalCreated)
def rotate_key(
    terminal_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    """Génère une nouvelle clé : l'ancienne cesse de fonctionner immédiatement (terminal perdu ou volé)."""
    terminal = TenantRepository(db, Terminal, org_id).get(terminal_id)
    if terminal is None:
        raise HTTPException(404, "Terminal introuvable")
    key = _new_key()
    terminal.key_hash, terminal.key_prefix = hash_terminal_key(key), key[:8]
    audit.record(
        db, action="terminal.key_rotated", actor=actor, organisation_id=org_id, object_type="terminal",
        object_id=str(terminal.id), ip=client_ip(request),
    )
    db.commit()
    return TerminalCreated.model_validate({**TerminalOut.model_validate(terminal).model_dump(), "key": key})


@router.delete("/{terminal_id}", status_code=204)
def delete_terminal(
    terminal_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    terminal = TenantRepository(db, Terminal, org_id).get(terminal_id)
    if terminal is None:
        raise HTTPException(404, "Terminal introuvable")
    name = terminal.name
    db.delete(terminal)
    audit.record(
        db, action="terminal.deleted", actor=actor, organisation_id=org_id, object_type="terminal",
        object_id=str(terminal_id), ip=client_ip(request), details={"name": name},
    )
    db.commit()
    return Response(status_code=204)
