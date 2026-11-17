import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    action: str
    object_type: str | None
    object_id: str | None
    ip_address: str | None
    details: dict
    created_at: datetime
