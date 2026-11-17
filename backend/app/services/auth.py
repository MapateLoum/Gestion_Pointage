from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import (
    burn_password_check,
    create_access_token,
    generate_refresh_token,
    hash_token,
    verify_password,
)
from app.core.time import as_utc, utcnow
from app.models import RefreshToken, User
from app.schemas.auth import TokenPair
from app.services import audit

INVALID_CREDENTIALS = "Email ou mot de passe incorrect"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


def issue_tokens(db: Session, user: User, user_agent: str | None) -> TokenPair:
    access, expires_in = create_access_token(
        user_id=user.id, role=user.role, organisation_id=user.organisation_id
    )
    raw_refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    return TokenPair(access_token=access, refresh_token=raw_refresh, expires_in=expires_in)


def login(
    db: Session, *, email: str, password: str, ip: str | None, user_agent: str | None
) -> TokenPair:
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()

    if user is None:
        burn_password_check(password)
        audit.record(db, action="auth.login_failed", ip=ip, details={"email": email, "reason": "unknown_user"})
        db.commit()
        raise _unauthorized(INVALID_CREDENTIALS)

    if user.locked_until is not None and as_utc(user.locked_until) > now:
        audit.record(db, action="auth.login_blocked", actor=user, ip=ip, details={"reason": "locked"})
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Compte temporairement verrouillé suite à trop de tentatives. Réessayez plus tard.",
        )

    if not user.is_active or not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        action = "auth.login_failed"
        if user.failed_login_attempts >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_attempts = 0
            action = "auth.account_locked"
        audit.record(db, action=action, actor=user, ip=ip, details={"reason": "bad_credentials"})
        db.commit()
        raise _unauthorized(INVALID_CREDENTIALS)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = issue_tokens(db, user, user_agent)
    audit.record(db, action="auth.login_success", actor=user, ip=ip)
    db.commit()
    return tokens


def refresh(db: Session, *, raw_token: str, ip: str | None, user_agent: str | None) -> TokenPair:
    now = utcnow()
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if token is None:
        raise _unauthorized("Jeton de rafraîchissement invalide")

    user = db.get(User, token.user_id)

    if token.revoked_at is not None:
        # Un jeton déjà utilisé qui revient = probable vol : on coupe toutes les sessions.
        active = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        for t in active:
            t.revoked_at = now
        audit.record(db, action="auth.refresh_reuse_detected", actor=user, ip=ip)
        db.commit()
        raise _unauthorized("Jeton de rafraîchissement invalide")

    if as_utc(token.expires_at) <= now or user is None or not user.is_active:
        raise _unauthorized("Jeton de rafraîchissement expiré")

    token.revoked_at = now  # rotation : un jeton ne sert qu'une fois
    tokens = issue_tokens(db, user, user_agent)
    audit.record(db, action="auth.token_refreshed", actor=user, ip=ip)
    db.commit()
    return tokens


def logout(db: Session, *, raw_token: str, ip: str | None) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if token is not None and token.revoked_at is None:
        token.revoked_at = utcnow()
        user = db.get(User, token.user_id)
        audit.record(db, action="auth.logout", actor=user, ip=ip)
        db.commit()
