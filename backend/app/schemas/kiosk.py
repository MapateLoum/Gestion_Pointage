import json
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Frame = Annotated[str, StringConstraints(min_length=100, max_length=2_200_000)]


class TerminalInfoOut(BaseModel):
    id: uuid.UUID
    name: str
    site_name: str | None
    organisation_name: str
    fingerprint_required: bool
    timezone: str
    server_time: datetime


class ChallengeOut(BaseModel):
    challenge_id: uuid.UUID
    steps: list[str]
    ttl_seconds: int
    max_frames: int


class AttemptIn(BaseModel):
    challenge_id: uuid.UUID
    frames: list[Frame] = Field(min_length=6, max_length=40)


class FingerprintIn(BaseModel):
    credential: dict

    @field_validator("credential")
    @classmethod
    def _limit(cls, value: dict) -> dict:
        if len(json.dumps(value)) > 30_000:
            raise ValueError("Réponse de l'authentificateur trop volumineuse")
        return value


class PersonBrief(BaseModel):
    display_name: str


class RecordBrief(BaseModel):
    id: uuid.UUID
    kind: str
    occurred_at: datetime
    method: str


class AttemptOut(BaseModel):
    status: str  # pending_fingerprint | success | failed | rejected
    attempt_id: uuid.UUID
    reason: str | None = None
    message: str | None = None
    person: PersonBrief | None = None
    webauthn: dict | None = None
    expires_in: int | None = None
    record: RecordBrief | None = None


# ----- administration des terminaux
class TerminalCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    site_id: uuid.UUID | None = None
    fingerprint_required: bool = True


class TerminalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    site_id: uuid.UUID | None = None
    fingerprint_required: bool | None = None
    is_active: bool | None = None


class TerminalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    site_id: uuid.UUID | None
    name: str
    key_prefix: str
    fingerprint_required: bool
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime


class TerminalCreated(TerminalOut):
    key: str  # affichée UNE SEULE fois


# ----- consultation des pointages
class RecordOut(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    matricule: str
    kind: str
    occurred_at: datetime
    terminal_name: str | None
    method: str
    face_score: float | None


class RecordPage(BaseModel):
    items: list[RecordOut]
    total: int
    limit: int
    offset: int


class AttemptRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    terminal_name: str | None
    person_name: str | None
    status: str
    reason: str | None
    face_score: float | None
    face_margin: float | None
    details: dict
