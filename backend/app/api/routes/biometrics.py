import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.biometrics import consent as consent_text
from app.biometrics.face import images as image_loader
from app.biometrics.face import service as face_service
from app.biometrics.face.engine import get_face_engine
from app.biometrics.face.types import EngineNotReady, FaceEngine, Pose
from app.config import settings
from app.core import crypto
from app.core.db_utils import commit_or_conflict
from app.core.deps import OrgScope, client_ip, get_org_scope, get_write_org_id, require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.core.time import utcnow
from app.database import get_db
from app.models import BiometricConsent, FaceTemplate, FingerprintCredential, Organisation, Person, User
from app.repositories.base import TenantRepository
from app.schemas.biometrics import (
    AnalyzeOut,
    AnalyzeRequest,
    BiometricsOut,
    ConsentCreate,
    ConsentOut,
    ConsentTextOut,
    EngineStatusOut,
    EnrollOut,
    EnrollRequest,
    FaceSummary,
    FingerprintCredentialOut,
    FingerprintSummary,
    IssueOut,
    PoseAngles,
)
from app.services import audit

router = APIRouter(tags=["biometrics"])


def _person(db: Session, org_id: uuid.UUID | None, person_id: uuid.UUID) -> Person:
    person = TenantRepository(db, Person, org_id).get(person_id)
    if person is None:
        raise HTTPException(404, "Personne introuvable")
    return person


def _active_consent(db: Session, person_id: uuid.UUID) -> BiometricConsent | None:
    return db.scalar(
        select(BiometricConsent).where(BiometricConsent.person_id == person_id, BiometricConsent.revoked_at.is_(None))
    )


def _require_consent(db: Session, person_id: uuid.UUID) -> BiometricConsent:
    consent = _active_consent(db, person_id)
    if consent is None:
        raise HTTPException(409, "Le consentement de la personne doit être enregistré avant toute capture")
    return consent


def _summary(db: Session, person_id: uuid.UUID) -> FaceSummary:
    rows = db.execute(
        select(FaceTemplate.pose, FaceTemplate.created_at, FaceTemplate.model_name).where(
            FaceTemplate.person_id == person_id
        )
    ).all()
    return FaceSummary(
        enrolled=len(rows) > 0,
        templates=len(rows),
        poses=sorted(r.pose for r in rows),
        enrolled_at=max((r.created_at for r in rows), default=None),
        model_name=rows[0].model_name if rows else None,
    )


def _fingerprint_summary(db: Session, person_id: uuid.UUID) -> FingerprintSummary:
    rows = db.scalars(
        select(FingerprintCredential).where(FingerprintCredential.person_id == person_id).order_by(FingerprintCredential.created_at)
    ).all()
    return FingerprintSummary(
        registered=len(rows) > 0,
        credentials=[FingerprintCredentialOut.model_validate(r) for r in rows],
        max_credentials=settings.max_fingerprints_per_person,
    )


def _not_ready(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ------------------------------------------------------------------ état du moteur

@router.get("/face/status", response_model=EngineStatusOut)
def face_status(
    engine: FaceEngine = Depends(get_face_engine),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    status = engine.status()
    try:
        crypto.ensure_configured()
        configured = True
    except crypto.CryptoNotConfigured:
        configured = False
    return EngineStatusOut(
        state=status.state,
        ready=status.state == "ready",
        model_name=status.model_name,
        error=status.error,
        encryption_configured=configured,
    )


# ------------------------------------------------------------------ consentement

@router.get("/persons/{person_id}/consent-text", response_model=ConsentTextOut)
def get_consent_text(
    person_id: uuid.UUID,
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    person = _person(db, scope.org_id, person_id)
    org = db.get(Organisation, person.organisation_id)
    return ConsentTextOut(
        version=consent_text.CONSENT_VERSION,
        text=consent_text.render(org.name),
        organisation=org.name,
    )


@router.get("/persons/{person_id}/biometrics", response_model=BiometricsOut)
def get_biometrics(
    person_id: uuid.UUID,
    db: Session = Depends(get_db),
    scope: OrgScope = Depends(get_org_scope),
    _: User = Depends(require_roles(*READ_ROLES)),
):
    person = _person(db, scope.org_id, person_id)
    consent = _active_consent(db, person.id)
    return BiometricsOut(
        consent=ConsentOut.model_validate(consent) if consent else None,
        consent_current=bool(consent and consent.text_version == consent_text.CONSENT_VERSION),
        current_consent_version=consent_text.CONSENT_VERSION,
        face=_summary(db, person.id),
        fingerprint=_fingerprint_summary(db, person.id),
    )


@router.post("/persons/{person_id}/consent", response_model=ConsentOut, status_code=201)
def record_consent(
    person_id: uuid.UUID,
    payload: ConsentCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    if payload.text_version != consent_text.CONSENT_VERSION:
        raise HTTPException(422, "Le texte de consentement a changé : recharge la page et relis-le")
    existing = _active_consent(db, person.id)
    if existing is not None:
        if existing.text_version == consent_text.CONSENT_VERSION:
            raise HTTPException(409, "Un consentement est déjà enregistré pour cette personne")
        # Un texte plus récent remplace l'ancien consentement ; les données déjà enrôlées sont conservées.
        existing.revoked_at = utcnow()
        existing.revoked_by_user_id = actor.id
        db.flush()  # libère l'unicité « un seul consentement actif » avant d'insérer le nouveau
        audit.record(
            db, action="consent.superseded", actor=actor, organisation_id=org_id, object_type="person",
            object_id=str(person.id), ip=client_ip(request),
            details={"old_version": existing.text_version, "new_version": consent_text.CONSENT_VERSION},
        )

    consent = BiometricConsent(
        organisation_id=org_id,
        person_id=person.id,
        text_version=payload.text_version,
        text_sha256=consent_text.template_sha256(),
        given_by=payload.given_by,
        signer_name=payload.signer_name.strip(),
        ip_address=client_ip(request),
        recorded_by_user_id=actor.id,
    )
    db.add(consent)
    db.flush()
    audit.record(
        db, action="consent.recorded", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request),
        details={"given_by": payload.given_by, "version": payload.text_version},
    )
    commit_or_conflict(db, "Un consentement est déjà enregistré pour cette personne")
    return consent


@router.delete("/persons/{person_id}/consent", status_code=204)
def revoke_consent(
    person_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    """Retirer le consentement supprime aussitôt les données biométriques de la personne."""
    person = _person(db, org_id, person_id)
    consent = _active_consent(db, person.id)
    if consent is None:
        raise HTTPException(404, "Aucun consentement actif")
    consent.revoked_at = utcnow()
    consent.revoked_by_user_id = actor.id
    deleted = db.execute(delete(FaceTemplate).where(FaceTemplate.person_id == person.id)).rowcount
    fingerprints = db.execute(delete(FingerprintCredential).where(FingerprintCredential.person_id == person.id)).rowcount
    audit.record(
        db, action="consent.revoked", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request),
        details={"templates_deleted": deleted, "fingerprints_deleted": fingerprints},
    )
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ visage

@router.post("/persons/{person_id}/face/analyze", response_model=AnalyzeOut)
def analyze_face(
    person_id: uuid.UUID,
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
    engine: FaceEngine = Depends(get_face_engine),
    _: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    """Contrôle une image en direct pendant la capture. Rien n'est enregistré."""
    person = _person(db, org_id, person_id)
    _require_consent(db, person.id)
    try:
        image = image_loader.load_image(payload.image)
        reference = Pose(**payload.reference.model_dump()) if payload.reference else None
        result = face_service.analyze_frame(engine, image, payload.pose, reference)
    except image_loader.ImageError as exc:
        raise HTTPException(422, exc.message)
    except EngineNotReady as exc:
        return _not_ready(exc)
    return AnalyzeOut(
        ok=result.ok,
        face_count=result.face_count,
        issues=[IssueOut(code=i.code, message=i.message) for i in result.issues],
        pose=PoseAngles(yaw=result.pose.yaw, pitch=result.pose.pitch, roll=result.pose.roll) if result.pose else None,
        metrics=result.metrics,
    )


@router.post("/persons/{person_id}/face/enroll", response_model=EnrollOut, status_code=201)
def enroll_face(
    person_id: uuid.UUID,
    payload: EnrollRequest,
    request: Request,
    db: Session = Depends(get_db),
    engine: FaceEngine = Depends(get_face_engine),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    _require_consent(db, person.id)
    try:
        crypto.ensure_configured()
    except crypto.CryptoNotConfigured as exc:
        return _not_ready(
            Exception(f"Chiffrement non configuré ({exc}). Ajoute FACE_ENCRYPTION_KEY dans le fichier .env.")
        )

    poses = [i.pose for i in payload.images]
    if sorted(poses) != sorted(face_service.POSES):
        raise HTTPException(422, "Il faut exactement une image par pose : face, gauche, droite, haut, bas")

    decoded = {}
    bad: dict[str, list[dict]] = {}
    for item in payload.images:
        try:
            decoded[item.pose] = image_loader.load_image(item.image)
        except image_loader.ImageError as exc:
            bad[item.pose] = [{"code": exc.code, "message": exc.message}]
    if bad:
        return JSONResponse(status_code=422, content={"detail": "Certaines images sont invalides", "poses": bad})

    try:
        result = face_service.enroll(db, engine, person, decoded)
    except EngineNotReady as exc:
        return _not_ready(exc)
    except crypto.DecryptionError:
        return _not_ready(
            Exception("Des gabarits existants sont illisibles avec la clé actuelle (FACE_ENCRYPTION_KEY modifiée ?)")
        )
    except face_service.EnrollmentRejected as exc:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Certaines captures sont à refaire",
                "poses": {n: [{"code": i.code, "message": i.message} for i in issues] for n, issues in exc.by_pose.items()},
            },
        )
    except face_service.DuplicateFound as dup:
        audit.record(
            db, action="face.duplicate_rejected", actor=actor, organisation_id=org_id, object_type="person",
            object_id=str(person.id), ip=client_ip(request),
            details={"matched_person_id": str(dup.person_id), "similarity": dup.similarity},
        )
        db.commit()
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"Ce visage correspond déjà à {dup.name} ({dup.matricule}).",
                "duplicate": {"person_id": str(dup.person_id), "matricule": dup.matricule, "name": dup.name},
            },
        )

    audit.record(
        db, action="face.enrolled", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request),
        details={"templates": result.templates, "model": engine.model_name, "quality": result.average_quality},
    )
    commit_or_conflict(db)
    return EnrollOut(templates=result.templates, poses=result.poses, average_quality=result.average_quality)


@router.delete("/persons/{person_id}/face", status_code=204)
def delete_face(
    person_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    deleted = db.execute(delete(FaceTemplate).where(FaceTemplate.person_id == person.id)).rowcount
    if deleted == 0:
        raise HTTPException(404, "Aucune donnée de visage pour cette personne")
    audit.record(
        db, action="face.deleted", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request), details={"templates_deleted": deleted},
    )
    db.commit()
    return Response(status_code=204)
