import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.biometrics import consent as consent_text
from app.biometrics.fingerprint import webauthn_provider as provider
from app.biometrics.fingerprint.webauthn_provider import FingerprintError
from app.core.db_utils import commit_or_conflict
from app.core.deps import client_ip, get_write_org_id, require_roles
from app.core.permissions import WRITE_ROLES
from app.database import get_db
from app.models import BiometricConsent, FingerprintCredential, Person, User
from app.repositories.base import TenantRepository
from app.schemas.biometrics import (
    AuthenticationResultOut,
    AuthenticationVerifyIn,
    FingerprintCredentialOut,
    RegistrationOptionsOut,
    RegistrationVerifyIn,
)
from app.services import audit

router = APIRouter(tags=["fingerprint"])


def _person(db: Session, org_id: uuid.UUID, person_id: uuid.UUID) -> Person:
    person = TenantRepository(db, Person, org_id).get(person_id)
    if person is None:
        raise HTTPException(404, "Personne introuvable")
    return person


def _require_current_consent(db: Session, person: Person) -> None:
    consent = db.scalar(
        select(BiometricConsent).where(BiometricConsent.person_id == person.id, BiometricConsent.revoked_at.is_(None))
    )
    if consent is None:
        raise HTTPException(409, "Le consentement de la personne doit être enregistré avant toute capture")
    if consent.text_version != consent_text.CONSENT_VERSION:
        raise HTTPException(
            409, "Le texte de consentement a été mis à jour (il mentionne maintenant l'empreinte) : renouvelle le consentement"
        )


def _fail(exc: FingerprintError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


@router.post("/persons/{person_id}/fingerprint/register/options", response_model=RegistrationOptionsOut)
def registration_options(
    person_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    _require_current_consent(db, person)
    try:
        challenge_id, options = provider.begin_registration(db, person)
    except FingerprintError as exc:
        raise _fail(exc)
    db.commit()
    return RegistrationOptionsOut(challenge_id=challenge_id, options=options)


@router.post("/persons/{person_id}/fingerprint/register/verify", response_model=FingerprintCredentialOut, status_code=201)
def registration_verify(
    person_id: uuid.UUID,
    payload: RegistrationVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    _require_current_consent(db, person)
    try:
        credential = provider.finish_registration(db, person, payload.challenge_id, payload.credential, payload.label)
    except FingerprintError as exc:
        db.commit()  # le défi est « brûlé » même en cas d'échec
        raise _fail(exc)
    audit.record(
        db, action="fingerprint.registered", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request),
        details={"provider": credential.provider, "label": credential.label},
    )
    commit_or_conflict(db, "Cette empreinte est déjà enregistrée")
    return credential


@router.post("/persons/{person_id}/fingerprint/authenticate/options", response_model=RegistrationOptionsOut)
def authentication_options(
    person_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    """Test depuis l'administration : vérifie que l'empreinte enregistrée est bien reconnue."""
    person = _person(db, org_id, person_id)
    _require_current_consent(db, person)
    try:
        challenge_id, options = provider.begin_authentication(db, person)
    except FingerprintError as exc:
        raise _fail(exc)
    db.commit()
    return RegistrationOptionsOut(challenge_id=challenge_id, options=options)


@router.post("/persons/{person_id}/fingerprint/authenticate/verify", response_model=AuthenticationResultOut)
def authentication_verify(
    person_id: uuid.UUID,
    payload: AuthenticationVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    _require_current_consent(db, person)
    try:
        credential = provider.finish_authentication(db, person, payload.challenge_id, payload.credential)
    except FingerprintError as exc:
        audit.record(
            db,
            action="fingerprint.counter_regression" if exc.suspected_clone else "fingerprint.verify_failed",
            actor=actor, organisation_id=org_id, object_type="person", object_id=str(person.id),
            ip=client_ip(request), details={"reason": exc.message},
        )
        db.commit()
        raise _fail(exc)
    audit.record(
        db, action="fingerprint.verified", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request), details={"label": credential.label},
    )
    db.commit()
    return AuthenticationResultOut(verified=True, credential_id=credential.id, label=credential.label)


@router.delete("/persons/{person_id}/fingerprint/{credential_id}", status_code=204)
def delete_fingerprint(
    person_id: uuid.UUID,
    credential_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(*WRITE_ROLES)),
    org_id: uuid.UUID = Depends(get_write_org_id),
):
    person = _person(db, org_id, person_id)
    deleted = db.execute(
        delete(FingerprintCredential).where(
            FingerprintCredential.id == credential_id, FingerprintCredential.person_id == person.id
        )
    ).rowcount
    if deleted == 0:
        raise HTTPException(404, "Empreinte introuvable")
    audit.record(
        db, action="fingerprint.deleted", actor=actor, organisation_id=org_id, object_type="person",
        object_id=str(person.id), ip=client_ip(request),
    )
    db.commit()
    return Response(status_code=204)
