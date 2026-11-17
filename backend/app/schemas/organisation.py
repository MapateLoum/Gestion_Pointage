import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    type: Literal["ecole", "entreprise", "chantier", "centre_formation", "autre"] = "entreprise"
    country: str = Field(default="SN", min_length=2, max_length=2)


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    country: str
    status: str
    created_at: datetime
