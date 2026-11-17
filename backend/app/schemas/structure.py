import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

GroupKind = Literal["classe", "equipe", "autre"]


def _check_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Fuseau horaire inconnu (exemple : Africa/Dakar)")
    return value


# ----- Sites -----
class SiteCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    timezone: str = "Africa/Dakar"

    _tz = field_validator("timezone")(_check_timezone)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    timezone: str | None = None
    is_active: bool | None = None

    _tz = field_validator("timezone")(_check_timezone)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    address: str | None
    timezone: str
    is_active: bool
    created_at: datetime


# ----- Départements -----
class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    site_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    site_id: uuid.UUID | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    site_id: uuid.UUID | None
    created_at: datetime


# ----- Groupes -----
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: GroupKind = "equipe"
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: GroupKind | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    kind: str
    site_id: uuid.UUID | None
    department_id: uuid.UUID | None
    created_at: datetime
