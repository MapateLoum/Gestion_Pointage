from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite renvoie des datetimes sans fuseau ; PostgreSQL en renvoie avec.
    On normalise pour pouvoir comparer sans erreur."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
