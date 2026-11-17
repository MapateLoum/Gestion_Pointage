import uuid
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.biometrics.face import gallery, liveness
from app.biometrics.face import service as face_service
from app.biometrics.face.types import FaceEngine
from app.biometrics.fingerprint import webauthn_provider as fingerprint
from app.biometrics.fingerprint.webauthn_provider import FingerprintError
from app.config import settings
from app.core.time import as_utc, utcnow
from app.models import AttendanceAttempt, AttendanceRecord, FingerprintCredential, KioskChallenge, Person, Terminal
from app.services import attendance

FAILURE_STATUSES = ("failed_liveness", "failed_face", "failed_fingerprint")

MESSAGES = {
    "unknown": "Visage non reconnu",
    "ambiguous": "Visage ambigu : réessaie, ou signale-toi à l'administrateur",
    "person_suspended": "Accès suspendu : contacte l'administrateur",
    "no_fingerprint": "Aucune empreinte enregistrée : contacte l'administrateur",
    "fingerprint_failed": "L'empreinte ne correspond pas",
}


class KioskLocked(Exception):
    def __init__(self, retry_after: int):
        super().__init__("terminal bloqué temporairement")
        self.retry_after = retry_after


class KioskError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class AttemptResult:
    attempt: AttendanceAttempt
    status: str  # "pending_fingerprint" | "success" | "failed" | "rejected"
    message: str | None = None
    person: Person | None = None
    webauthn: dict | None = None
    record: AttendanceRecord | None = None


def display_name(person: Person) -> str:
    return f"{person.first_name} {person.last_name[:1]}.".strip()


def check_lockout(db: Session, terminal: Terminal) -> None:
    """Après trop d'échecs rapprochés, le terminal se bloque quelques secondes (anti essais en rafale)."""
    now = utcnow()
    since = now - timedelta(seconds=settings.kiosk_failure_window_seconds)
    count, last = db.execute(
        select(func.count(AttendanceAttempt.id), func.max(AttendanceAttempt.created_at)).where(
            AttendanceAttempt.terminal_id == terminal.id,
            AttendanceAttempt.status.in_(FAILURE_STATUSES),
            AttendanceAttempt.created_at > since,
        )
    ).one()
    if count >= settings.kiosk_max_failures and last is not None:
        remaining = settings.kiosk_lockout_seconds - (now - as_utc(last)).total_seconds()
        if remaining > 0:
            raise KioskLocked(int(remaining) + 1)


def issue_challenge(db: Session, terminal: Terminal) -> KioskChallenge:
    now = utcnow()
    challenge = KioskChallenge(
        organisation_id=terminal.organisation_id,
        terminal_id=terminal.id,
        steps=liveness.new_steps(),
        expires_at=now + timedelta(seconds=settings.kiosk_challenge_ttl_seconds),
    )
    db.add(challenge)
    db.flush()
    return challenge


def _consume_challenge(db: Session, terminal: Terminal, challenge_id: uuid.UUID) -> list[str]:
    challenge = db.get(KioskChallenge, challenge_id)
    if challenge is None or challenge.terminal_id != terminal.id:
        raise KioskError("Défi inconnu : recommence le pointage")
    claimed = db.execute(
        update(KioskChallenge)
        .where(KioskChallenge.id == challenge.id, KioskChallenge.consumed_at.is_(None), KioskChallenge.expires_at > utcnow())
        .values(consumed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise KioskError("Défi expiré ou déjà utilisé : recommence le pointage")
    return list(challenge.steps)


def _fail(db: Session, attempt: AttendanceAttempt, status: str, reason: str, message: str, **details) -> AttemptResult:
    attempt.status, attempt.reason = status, reason
    attempt.details = {**attempt.details, **details}
    attempt.completed_at = utcnow()
    db.flush()
    return AttemptResult(attempt, "failed" if status in FAILURE_STATUSES else "rejected", message)


def _finish_success(
    db: Session, terminal: Terminal, attempt: AttendanceAttempt, person: Person, method: str
) -> AttemptResult:
    try:
        record = attendance.record_attendance(
            db, person=person, terminal=terminal, attempt_id=attempt.id, method=method, face_score=attempt.face_score
        )
    except attendance.TooSoon as exc:
        return _fail(
            db, attempt, "rejected", "too_soon", f"Déjà pointé il y a {exc.seconds_ago} s : patiente un instant", seconds_ago=exc.seconds_ago
        )
    attempt.status, attempt.reason, attempt.completed_at = "success", None, utcnow()
    db.flush()
    return AttemptResult(attempt, "success", person=person, record=record)


def process_attempt(
    db: Session, engine: FaceEngine, terminal: Terminal, challenge_id: uuid.UUID, images: list[np.ndarray | None]
) -> AttemptResult:
    steps = _consume_challenge(db, terminal, challenge_id)
    attempt = AttendanceAttempt(organisation_id=terminal.organisation_id, terminal_id=terminal.id, status="started", details={"steps": steps})
    db.add(attempt)
    db.flush()

    frames = [face_service.analyze_basic(engine, img) if img is not None else liveness.FrameInfo(0) for img in images]
    outcome = liveness.evaluate(frames, steps)
    if not outcome.ok:
        return _fail(db, attempt, "failed_liveness", (outcome.reason or "liveness").split(":")[0], outcome.message or "Vérification de vivacité échouée", **outcome.details)
    attempt.details = {**attempt.details, **outcome.details}

    match = gallery.identify(db, terminal.organisation_id, engine.model_name, outcome.probe)
    attempt.face_score, attempt.face_margin = match.score, match.margin
    if match.person_id is None:
        return _fail(db, attempt, "failed_face", match.reason or "unknown", MESSAGES[match.reason or "unknown"])

    person = db.get(Person, match.person_id)
    attempt.person_id = person.id
    if person.status != "active":
        return _fail(db, attempt, "rejected", "person_suspended", MESSAGES["person_suspended"])

    if not terminal.fingerprint_required:
        return _finish_success(db, terminal, attempt, person, "face")

    has_fingerprint = db.scalar(select(func.count(FingerprintCredential.id)).where(FingerprintCredential.person_id == person.id))
    if not has_fingerprint:
        return _fail(db, attempt, "rejected", "no_fingerprint", MESSAGES["no_fingerprint"])

    challenge_id_webauthn, options = fingerprint.begin_authentication(db, person)
    attempt.status = "pending_fingerprint"
    attempt.webauthn_challenge_id = challenge_id_webauthn
    attempt.expires_at = utcnow() + timedelta(seconds=settings.kiosk_attempt_ttl_seconds)
    db.flush()
    return AttemptResult(
        attempt, "pending_fingerprint", person=person, webauthn={"challenge_id": challenge_id_webauthn, "options": options}
    )


def complete_fingerprint(db: Session, terminal: Terminal, attempt_id: uuid.UUID, credential: dict) -> AttemptResult:
    attempt = db.get(AttendanceAttempt, attempt_id)
    if attempt is None or attempt.terminal_id != terminal.id:
        raise KioskError("Tentative inconnue", 404)
    claimed = db.execute(
        update(AttendanceAttempt)
        .where(
            AttendanceAttempt.id == attempt.id,
            AttendanceAttempt.status == "pending_fingerprint",
            AttendanceAttempt.expires_at > utcnow(),
        )
        .values(status="completing")
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.refresh(attempt)
        if attempt.status == "pending_fingerprint":  # elle a simplement expiré
            attempt.status, attempt.reason, attempt.completed_at = "expired", "expired", utcnow()
            db.flush()
            raise KioskError("Temps écoulé : recommence le pointage", 410)
        raise KioskError("Cette tentative est déjà terminée", 409)
    db.refresh(attempt)

    person = db.get(Person, attempt.person_id)
    try:
        fingerprint.finish_authentication(db, person, attempt.webauthn_challenge_id, credential)
    except FingerprintError as exc:
        return _fail(db, attempt, "failed_fingerprint", "fingerprint_failed", MESSAGES["fingerprint_failed"], detail=exc.message)
    return _finish_success(db, terminal, attempt, person, "face+fingerprint")
