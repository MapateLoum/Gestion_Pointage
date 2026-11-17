import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Category = Literal["employe", "enseignant", "eleve", "autre"]
PersonStatus = Literal["active", "suspended"]

MATRICULE_PATTERN = r"^[A-Za-z0-9._/\-]{1,50}$"
PHONE_PATTERN = r"^[0-9+()\-\s.]{6,30}$"


class PersonCreate(BaseModel):
    matricule: str = Field(pattern=MATRICULE_PATTERN)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    category: Category = "employe"
    status: PersonStatus = "active"
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class PersonUpdate(BaseModel):
    matricule: str | None = Field(default=None, pattern=MATRICULE_PATTERN)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    category: Category | None = None
    status: PersonStatus | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    group_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    matricule: str
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    category: str
    status: str
    site_id: uuid.UUID | None
    department_id: uuid.UUID | None
    group_ids: list[uuid.UUID]
    face_enrolled: bool
    fingerprint_enrolled: bool
    consent_active: bool
    created_at: datetime


class PersonPage(BaseModel):
    items: list[PersonOut]
    total: int
    limit: int
    offset: int


class ImportErrorOut(BaseModel):
    line: int
    message: str


class ImportResult(BaseModel):
    dry_run: bool
    total_rows: int
    valid_rows: int
    imported: int
    groups_created: int
    errors: list[ImportErrorOut]
