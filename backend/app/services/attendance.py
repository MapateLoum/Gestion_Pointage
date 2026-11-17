import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.time import as_utc, utcnow
from app.models import AttendanceRecord, Person, Site, Terminal


class TooSoon(Exception):
    def __init__(self, seconds_ago: int):
        super().__init__("pointage trop rapproché")
        self.seconds_ago = seconds_ago


def terminal_timezone(db: Session, terminal: Terminal) -> str:
    if terminal.site_id:
        tz = db.scalar(select(Site.timezone).where(Site.id == terminal.site_id))
        if tz:
            return tz
    return settings.default_timezone


def local_day_bounds(tz_name: str, day: date | None = None, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Début et fin (en UTC) d'une journée locale : « aujourd'hui » dépend du fuseau du site."""
    tz = ZoneInfo(tz_name)
    day = day or (now or utcnow()).astimezone(tz).date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(ZoneInfo("UTC")), (start + timedelta(days=1)).astimezone(ZoneInfo("UTC"))


def record_attendance(
    db: Session,
    *,
    person: Person,
    terminal: Terminal,
    attempt_id: uuid.UUID,
    method: str,
    face_score: float | None,
) -> AttendanceRecord:
    """Enregistre une entrée ou une sortie : on alterne selon le dernier pointage DE LA JOURNÉE locale."""
    now = utcnow()
    last_any = db.scalar(
        select(AttendanceRecord).where(AttendanceRecord.person_id == person.id).order_by(AttendanceRecord.occurred_at.desc()).limit(1)
    )
    if last_any is not None:
        elapsed = (now - as_utc(last_any.occurred_at)).total_seconds()
        if elapsed < settings.attendance_min_interval_seconds:
            raise TooSoon(int(elapsed))

    start, end = local_day_bounds(terminal_timezone(db, terminal), now=now)
    last_today = db.scalar(
        select(AttendanceRecord)
        .where(AttendanceRecord.person_id == person.id, AttendanceRecord.occurred_at >= start, AttendanceRecord.occurred_at < end)
        .order_by(AttendanceRecord.occurred_at.desc())
        .limit(1)
    )
    kind = "out" if last_today is not None and last_today.kind == "in" else "in"
    row = AttendanceRecord(
        organisation_id=person.organisation_id,
        person_id=person.id,
        terminal_id=terminal.id,
        attempt_id=attempt_id,
        kind=kind,
        occurred_at=now,
        method=method,
        face_score=face_score,
    )
    db.add(row)
    db.flush()
    return row
