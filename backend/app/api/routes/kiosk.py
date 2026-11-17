"""API du terminal de pointage. Authentification par clé de terminal (en-tête X-Terminal-Key), pas par compte utilisateur."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.biometrics.face import images as image_loader
from app.biometrics.face.engine import get_face_engine
from app.biometrics.face.types import EngineNotReady, FaceEngine
from app.config import settings
from app.core.deps import get_terminal
from app.core.time import utcnow
from app.database import get_db
from app.models import Organisation, Site, Terminal
from app.schemas.kiosk import (
    AttemptIn,
    AttemptOut,
    ChallengeOut,
    FingerprintIn,
    PersonBrief,
    RecordBrief,
    TerminalInfoOut,
)
from app.services import attendance, kiosk

router = APIRouter(prefix="/kiosk", tags=["kiosk"])


def _locked(exc: kiosk.KioskLocked) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Trop d'échecs : réessaie dans {exc.retry_after} s", "retry_after": exc.retry_after},
        headers={"Retry-After": str(exc.retry_after)},
    )


def _serialize(result: kiosk.AttemptResult) -> AttemptOut:
    attempt = result.attempt
    out = AttemptOut(status=result.status, attempt_id=attempt.id, reason=attempt.reason, message=result.message)
    if result.person is not None and result.status in ("pending_fingerprint", "success"):
        out.person = PersonBrief(display_name=kiosk.display_name(result.person))
    if result.webauthn is not None:
        out.webauthn = {"challenge_id": str(result.webauthn["challenge_id"]), "options": result.webauthn["options"]}
        out.expires_in = settings.kiosk_attempt_ttl_seconds
    if result.record is not None:
        out.record = RecordBrief(id=result.record.id, kind=result.record.kind, occurred_at=result.record.occurred_at, method=result.record.method)
    return out


@router.get("/me", response_model=TerminalInfoOut)
def me(terminal: Terminal = Depends(get_terminal), db: Session = Depends(get_db)):
    terminal.last_seen_at = utcnow()
    org = db.get(Organisation, terminal.organisation_id)
    site_name = db.scalar(select(Site.name).where(Site.id == terminal.site_id)) if terminal.site_id else None
    db.commit()
    return TerminalInfoOut(
        id=terminal.id,
        name=terminal.name,
        site_name=site_name,
        organisation_name=org.name,
        fingerprint_required=terminal.fingerprint_required,
        timezone=attendance.terminal_timezone(db, terminal),
        server_time=utcnow(),
    )


@router.post("/challenges", response_model=ChallengeOut)
def new_challenge(terminal: Terminal = Depends(get_terminal), db: Session = Depends(get_db)):
    try:
        kiosk.check_lockout(db, terminal)
    except kiosk.KioskLocked as exc:
        return _locked(exc)
    terminal.last_seen_at = utcnow()
    challenge = kiosk.issue_challenge(db, terminal)
    db.commit()
    return ChallengeOut(
        challenge_id=challenge.id,
        steps=list(challenge.steps),
        ttl_seconds=settings.kiosk_challenge_ttl_seconds,
        max_frames=settings.kiosk_max_frames,
    )


@router.post("/attempts", response_model=AttemptOut)
def submit_attempt(
    payload: AttemptIn,
    terminal: Terminal = Depends(get_terminal),
    db: Session = Depends(get_db),
    engine: FaceEngine = Depends(get_face_engine),
):
    if len(payload.frames) > settings.kiosk_max_frames:
        raise HTTPException(422, f"Trop d'images (maximum {settings.kiosk_max_frames})")
    try:
        kiosk.check_lockout(db, terminal)
    except kiosk.KioskLocked as exc:
        return _locked(exc)

    images = []
    for data in payload.frames:
        try:
            images.append(image_loader.load_image(data))
        except image_loader.ImageError:
            images.append(None)  # une image illisible compte simplement comme « pas de visage »

    try:
        result = kiosk.process_attempt(db, engine, terminal, payload.challenge_id, images)
    except kiosk.KioskError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.message)
    except EngineNotReady as exc:
        db.commit()  # le défi est consommé : on en redemandera un
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    terminal.last_seen_at = utcnow()
    db.commit()
    return _serialize(result)


@router.post("/attempts/{attempt_id}/fingerprint", response_model=AttemptOut)
def submit_fingerprint(
    attempt_id: uuid.UUID,
    payload: FingerprintIn,
    terminal: Terminal = Depends(get_terminal),
    db: Session = Depends(get_db),
):
    try:
        result = kiosk.complete_fingerprint(db, terminal, attempt_id, payload.credential)
    except kiosk.KioskError as exc:
        db.commit()  # conserve l'éventuel passage à « expiré »
        raise HTTPException(exc.status, exc.message)
    db.commit()
    return _serialize(result)
