import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db_utils import commit_or_conflict
from app.core.deps import OrgScope, client_ip, get_org_scope, get_write_org_id, require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.database import get_db
from app.models import Department, Group, Person, Site, User
from app.repositories.base import TenantRepository
from app.schemas.person import (
    ImportErrorOut,
    ImportResult,
    PersonCreate,
    PersonOut,
    PersonPage,
    PersonUpdate,
)
from app.services import audit, csv_import

router = APIRouter(prefix="/persons", tags=["persons"])


def _check_refs(db: Session, org_id: uuid.UUID, data: dict) -> None:
    if data.get("site_id") is not None and TenantRepository(db, Site, org_id).get(data["site_id"]) is None:
        raise HTTPException(422, "site_id invalide pour cette organisation")
    if (
        data.get("department_id") is not None
        and TenantRepository(db, Department, org_id).get(data["department_id"]) is None
    ):
        raise HTTPException(422, "department_id invalide pour cette organisation")


def _resolve_groups(db: Session, org_id: uuid.UUID, group_ids: list[uuid.UUID]) -> list[Group]:
    wanted = set(group_ids)
    if not wanted:
        return []
    found = list(
        db.scalars(select(Group).where(Group.organisation_id == org_id, Group.id.in_(wanted)))
    )
    if len(found) != len(wanted):
        raise HTTPException(422, "group_ids contient un groupe invalide pour cette organisation")
    return found


def _matricule_taken(db: Session, org_id: uuid.UUID, matricule: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Person.id).where(Person.organisation_id == org_id, Person.matricule == matricule)
    if exclude is not None:
        stmt = stmt.where(Person.id != exclude)
    return db.scalar(stmt) is not None


# --------------------------------------------------------------- import CSV
# (déclaré AVANT /{person_id} pour que « import-csv » ne soit pas pris pour un identifiant)

@router.get("/import-template")
def import_template(_: User = Depends(require_roles(*WRITE_ROLES))):
    return Response(
        content="\ufeff" + csv_import.TEMPLATE,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modele-import-personnes.csv"'},
    )


@router.post("/import-csv", response_model=ImportResult)
def import_csv(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Valide le fichier sans rien importer"),
    create_groups: bool = Query(False, description="Crée les groupes absents au lieu de signaler une erreur"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    raw = file.file.read(csv_import.MAX_BYTES + 1)
    if len(raw) > csv_import.MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (2 Mo maximum)")

    parsed = csv_import.parse_csv(db, org_id, raw, create_groups=create_groups)
    errors = [ImportErrorOut(line=e.line, message=e.message) for e in parsed.errors]

    if errors:
        body = ImportResult(
            dry_run=dry_run, total_rows=parsed.total_rows, valid_rows=len(parsed.rows),
            imported=0, groups_created=0, errors=errors,
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    if dry_run:
        return ImportResult(
            dry_run=True, total_rows=parsed.total_rows, valid_rows=len(parsed.rows),
            imported=0, groups_created=len(parsed.new_groups), errors=[],
        )

    group_map = {
        csv_import.norm(g.name): g
        for g in db.scalars(select(Group).where(Group.organisation_id == org_id))
    }
    for key, display_name in parsed.new_groups.items():
        group = Group(organisation_id=org_id, name=display_name, kind="autre")
        db.add(group)
        group_map[key] = group

    for row in parsed.rows:
        db.add(
            Person(
                organisation_id=org_id,
                matricule=row.matricule,
                first_name=row.first_name,
                last_name=row.last_name,
                email=row.email,
                phone=row.phone,
                category=row.category,
                site_id=row.site_id,
                department_id=row.department_id,
                groups=[group_map[k] for k in dict.fromkeys(row.group_keys)],
            )
        )
    audit.record(
        db, action="person.imported", actor=actor, organisation_id=org_id, object_type="person",
        ip=client_ip(request),
        details={"count": len(parsed.rows), "groups_created": len(parsed.new_groups)},
    )
    commit_or_conflict(db, "Conflit pendant l'import (matricule déjà utilisé ?)")
    return ImportResult(
        dry_run=False, total_rows=parsed.total_rows, valid_rows=len(parsed.rows),
        imported=len(parsed.rows), groups_created=len(parsed.new_groups), errors=[],
    )


# --------------------------------------------------------------------- CRUD

@router.get("", response_model=PersonPage)
def list_persons(
    q: str | None = Query(None, max_length=100, description="Recherche : nom, prénom ou matricule"),
    status: str | None = Query(None, pattern="^(active|suspended)$"),
    category: str | None = Query(None, pattern="^(employe|enseignant|eleve|autre)$"),
    site_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    stmt = TenantRepository(db, Person, scope.org_id).query()
    if q:
        stmt = stmt.where(
            Person.last_name.icontains(q, autoescape=True)
            | Person.first_name.icontains(q, autoescape=True)
            | Person.matricule.icontains(q, autoescape=True)
        )
    if status:
        stmt = stmt.where(Person.status == status)
    if category:
        stmt = stmt.where(Person.category == category)
    if site_id:
        stmt = stmt.where(Person.site_id == site_id)
    if department_id:
        stmt = stmt.where(Person.department_id == department_id)
    if group_id:
        stmt = stmt.where(Person.groups.any(Group.id == group_id))

    total = db.scalar(stmt.with_only_columns(func.count(Person.id)).order_by(None)) or 0
    items = list(
        db.scalars(stmt.order_by(Person.last_name, Person.first_name).limit(limit).offset(offset)).all()
    )
    return PersonPage(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=PersonOut, status_code=201)
def create_person(
    payload: PersonCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    data = payload.model_dump()
    group_ids = data.pop("group_ids")
    _check_refs(db, org_id, data)
    groups = _resolve_groups(db, org_id, group_ids)
    if _matricule_taken(db, org_id, data["matricule"]):
        raise HTTPException(409, "Ce matricule existe déjà dans l'organisation")
    if data["email"]:
        data["email"] = data["email"].lower()

    person = Person(organisation_id=org_id, groups=groups, **data)
    db.add(person)
    db.flush()
    audit.record(
        db, action="person.created", actor=actor, organisation_id=org_id,
        object_type="person", object_id=str(person.id), ip=client_ip(request),
        details={"matricule": person.matricule},
    )
    commit_or_conflict(db, "Ce matricule existe déjà dans l'organisation")
    return person


@router.get("/{person_id}", response_model=PersonOut)
def get_person(
    person_id: uuid.UUID,
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    person = TenantRepository(db, Person, scope.org_id).get(person_id)
    if person is None:
        raise HTTPException(404, "Personne introuvable")
    return person


@router.patch("/{person_id}", response_model=PersonOut)
def update_person(
    person_id: uuid.UUID,
    payload: PersonUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = TenantRepository(db, Person, org_id).get(person_id)
    if person is None:
        raise HTTPException(404, "Personne introuvable")

    data = payload.model_dump(exclude_unset=True)
    group_ids = data.pop("group_ids", None)
    for field in ("matricule", "first_name", "last_name", "category", "status"):
        if field in data and data[field] is None:
            raise HTTPException(422, f"{field} ne peut pas être vide")
    _check_refs(db, org_id, data)
    if "matricule" in data and _matricule_taken(db, org_id, data["matricule"], exclude=person.id):
        raise HTTPException(409, "Ce matricule existe déjà dans l'organisation")
    if data.get("email"):
        data["email"] = data["email"].lower()

    for field, value in data.items():
        setattr(person, field, value)
    changed = sorted(data.keys())
    if group_ids is not None:
        person.groups = _resolve_groups(db, org_id, group_ids)
        changed = sorted([*changed, "group_ids"])
    audit.record(
        db, action="person.updated", actor=actor, organisation_id=org_id,
        object_type="person", object_id=str(person.id), ip=client_ip(request),
        details={"fields": changed},
    )
    commit_or_conflict(db, "Ce matricule existe déjà dans l'organisation")
    return person


@router.delete("/{person_id}", status_code=204)
def delete_person(
    person_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = TenantRepository(db, Person, org_id).get(person_id)
    if person is None:
        raise HTTPException(404, "Personne introuvable")
    matricule = person.matricule
    db.delete(person)
    audit.record(
        db, action="person.deleted", actor=actor, organisation_id=org_id,
        object_type="person", object_id=str(person_id), ip=client_ip(request),
        details={"matricule": matricule},
    )
    db.commit()
    return Response(status_code=204)
