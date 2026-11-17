import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class TenantRepository(Generic[T]):
    """Seul point d'accès aux données d'un modèle qui porte organisation_id.
    Toute lecture est filtrée par organisation : c'est ce qui garantit
    l'isolation entre clients. org_id=None = accès global (super_admin)."""

    def __init__(self, db: Session, model: type[T], org_id: uuid.UUID | None):
        self.db = db
        self.model: Any = model
        self.org_id = org_id

    def query(self) -> Select:
        stmt = select(self.model)
        if self.org_id is not None:
            stmt = stmt.where(self.model.organisation_id == self.org_id)
        return stmt

    def get(self, obj_id: uuid.UUID) -> T | None:
        return self.db.scalar(self.query().where(self.model.id == obj_id))

    def list(self, limit: int = 50, offset: int = 0) -> list[T]:
        stmt = self.query()
        if hasattr(self.model, "created_at"):
            stmt = stmt.order_by(self.model.created_at.desc())
        return list(self.db.scalars(stmt.limit(limit).offset(offset)).all())

    def add(self, obj: T) -> T:
        if self.org_id is not None:
            obj.organisation_id = self.org_id  # type: ignore[attr-defined]
        self.db.add(obj)
        return obj
