import base64
import json
import logging
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import settings
from app.core.time import utcnow
from app.models import FingerprintCredential, Person, WebAuthnChallenge

logger = logging.getLogger("pointage.fingerprint")

PROVIDER_NAME = "webauthn"
DEFAULT_LABEL = "Empreinte de l'appareil"
TIMEOUT_MS = 120_000


class FingerprintError(Exception):
    def __init__(self, message: str, status: int = 400, *, suspected_clone: bool = False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.suspected_clone = suspected_clone


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _descriptors(credentials: list[FingerprintCredential]) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(id=_unb64(c.credential_id), transports=[AuthenticatorTransport.INTERNAL])
        for c in credentials
    ]


def _credentials_of(db: Session, person: Person) -> list[FingerprintCredential]:
    return list(db.scalars(select(FingerprintCredential).where(FingerprintCredential.person_id == person.id)))


# ------------------------------------------------------------------- défis à usage unique

def _store_challenge(db: Session, person: Person, purpose: str, challenge: bytes) -> uuid.UUID:
    now = utcnow()
    db.execute(delete(WebAuthnChallenge).where(WebAuthnChallenge.expires_at < now - timedelta(days=1)))
    row = WebAuthnChallenge(
        organisation_id=person.organisation_id,
        person_id=person.id,
        purpose=purpose,
        challenge=challenge,
        expires_at=now + timedelta(seconds=settings.webauthn_challenge_ttl_seconds),
    )
    db.add(row)
    db.flush()
    return row.id


def _consume_challenge(db: Session, challenge_id: uuid.UUID, person: Person, purpose: str) -> bytes:
    """Marque le défi comme utilisé (une seule fois) et le renvoie. Un défi brûlé ne resservira jamais,
    même si la vérification qui suit échoue : impossible de deviner une réponse par essais successifs."""
    row = db.get(WebAuthnChallenge, challenge_id)
    if row is None or row.person_id != person.id or row.purpose != purpose:
        raise FingerprintError("Défi inconnu : recommence l'opération.")
    claimed = db.execute(
        update(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == row.id,
            WebAuthnChallenge.consumed_at.is_(None),
            WebAuthnChallenge.expires_at > utcnow(),
        )
        .values(consumed_at=utcnow())
        .execution_options(synchronize_session=False)  # la comparaison de dates se fait dans la base
    )
    if claimed.rowcount != 1:
        raise FingerprintError("Défi déjà utilisé ou expiré : recommence l'opération.")
    db.refresh(row)
    return row.challenge


# ------------------------------------------------------------------- enregistrement

def begin_registration(db: Session, person: Person) -> tuple[uuid.UUID, dict]:
    existing = _credentials_of(db, person)
    if len(existing) >= settings.max_fingerprints_per_person:
        raise FingerprintError(
            f"Maximum {settings.max_fingerprints_per_person} empreintes par personne : supprime-en une d'abord.", 409
        )
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=person.id.bytes,  # identifiant opaque : ne contient aucune donnée personnelle
        user_name=person.matricule,
        user_display_name=f"{person.first_name} {person.last_name}",
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,  # lecteur de l'appareil lui-même
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.REQUIRED,  # le doigt (ou le code de l'appareil) est exigé
        ),
        exclude_credentials=_descriptors(existing),
        timeout=TIMEOUT_MS,
    )
    challenge_id = _store_challenge(db, person, "register", options.challenge)
    return challenge_id, json.loads(options_to_json(options))


def finish_registration(
    db: Session, person: Person, challenge_id: uuid.UUID, credential: dict, label: str | None
) -> FingerprintCredential:
    expected = _consume_challenge(db, challenge_id, person, "register")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=expected,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origins_list,
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        logger.warning("Enregistrement d'empreinte refusé : %s", exc)
        raise FingerprintError(f"L'enregistrement de l'empreinte a été refusé : {exc}")

    credential_id = _b64(verified.credential_id)
    if db.scalar(select(FingerprintCredential.id).where(FingerprintCredential.credential_id == credential_id)):
        raise FingerprintError("Cette empreinte est déjà enregistrée.", 409)

    row = FingerprintCredential(
        organisation_id=person.organisation_id,
        person_id=person.id,
        provider=PROVIDER_NAME,
        credential_id=credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        label=(label or "").strip() or DEFAULT_LABEL,
    )
    db.add(row)
    db.flush()
    return row


# ------------------------------------------------------------------- vérification

def begin_authentication(db: Session, person: Person) -> tuple[uuid.UUID, dict]:
    credentials = _credentials_of(db, person)
    if not credentials:
        raise FingerprintError("Aucune empreinte n'est enregistrée pour cette personne.", 409)
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        # Seuls les identifiants DE CETTE PERSONNE sont acceptés : c'est ce qui lie l'empreinte à l'identité.
        allow_credentials=_descriptors(credentials),
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=TIMEOUT_MS,
    )
    challenge_id = _store_challenge(db, person, "authenticate", options.challenge)
    return challenge_id, json.loads(options_to_json(options))


def finish_authentication(
    db: Session, person: Person, challenge_id: uuid.UUID, credential: dict
) -> FingerprintCredential:
    expected = _consume_challenge(db, challenge_id, person, "authenticate")
    credential_id = credential.get("id") if isinstance(credential, dict) else None
    row = None
    if isinstance(credential_id, str):
        row = db.scalar(
            select(FingerprintCredential).where(
                FingerprintCredential.person_id == person.id, FingerprintCredential.credential_id == credential_id
            )
        )
    if row is None:
        raise FingerprintError("Cette empreinte ne correspond pas à la personne.", 403)
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=expected,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origins_list,
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        logger.warning("Vérification d'empreinte refusée : %s", exc)
        raise FingerprintError(
            "La vérification de l'empreinte a échoué.", 403, suspected_clone="sign count" in str(exc).lower()
        )
    row.sign_count = verified.new_sign_count
    row.last_used_at = utcnow()
    return row
