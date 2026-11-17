import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    *,
    action: str,
    actor: User | None = None,
    organisation_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Ajoute une ligne au journal. L'appelant fait le commit."""
    if organisation_id is None and actor is not None:
        organisation_id = actor.organisation_id
    entry = AuditLog(
        organisation_id=organisation_id,
        actor_user_id=actor.id if actor else None,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip_address=ip,
        details=details or {},
    )
    db.add(entry)
    return entry
