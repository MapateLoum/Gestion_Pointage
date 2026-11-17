import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.roles import Role


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=128)
    role: Role
    # Utilisé uniquement par un super_admin (un admin d'organisation crée toujours
    # dans sa propre organisation).
    organisation_id: uuid.UUID | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    organisation_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
