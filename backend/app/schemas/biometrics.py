import uuid
from datetime import datetime
from typing import Literal

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

PoseName = Literal["front", "left", "right", "up", "down"]
# 1,5 Mo d'image ≈ 2 Mo en base64
ImageData = Field(min_length=100, max_length=2_200_000)


class ConsentCreate(BaseModel):
    text_version: str = Field(max_length=20)
    accepted: Literal[True]
    given_by: Literal["person", "guardian"]
    signer_name: str = Field(min_length=2, max_length=200)


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text_version: str
    given_by: str
    signer_name: str
    signed_at: datetime


class ConsentTextOut(BaseModel):
    version: str
    text: str
    organisation: str


class FaceSummary(BaseModel):
    enrolled: bool
    templates: int
    poses: list[str]
    enrolled_at: datetime | None
    model_name: str | None


class FingerprintCredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    label: str | None
    created_at: datetime
    last_used_at: datetime | None


class FingerprintSummary(BaseModel):
    registered: bool
    credentials: list[FingerprintCredentialOut]
    max_credentials: int


class BiometricsOut(BaseModel):
    consent: ConsentOut | None
    consent_current: bool  # le consentement signé correspond au texte actuellement en vigueur
    current_consent_version: str
    face: FaceSummary
    fingerprint: FingerprintSummary


class EngineStatusOut(BaseModel):
    state: str
    ready: bool
    model_name: str
    error: str | None
    encryption_configured: bool


class PoseAngles(BaseModel):
    yaw: float
    pitch: float
    roll: float = 0.0


class AnalyzeRequest(BaseModel):
    image: str = ImageData
    pose: PoseName
    reference: PoseAngles | None = None  # angles de la pose de face (pour juger les autres poses)


class IssueOut(BaseModel):
    code: str
    message: str


class AnalyzeOut(BaseModel):
    ok: bool
    face_count: int
    issues: list[IssueOut]
    pose: PoseAngles | None
    metrics: dict[str, float]


class EnrollImage(BaseModel):
    pose: PoseName
    image: str = ImageData


class EnrollRequest(BaseModel):
    images: list[EnrollImage] = Field(min_length=5, max_length=5)


class EnrollOut(BaseModel):
    templates: int
    poses: list[str]
    average_quality: float


def _limit_size(value: dict) -> dict:
    if len(json.dumps(value)) > 30_000:
        raise ValueError("Réponse de l'authentificateur trop volumineuse")
    return value


class RegistrationOptionsOut(BaseModel):
    challenge_id: uuid.UUID
    options: dict


class RegistrationVerifyIn(BaseModel):
    challenge_id: uuid.UUID
    credential: dict
    label: str | None = Field(default=None, max_length=100)

    _size = field_validator("credential")(_limit_size)


class AuthenticationVerifyIn(BaseModel):
    challenge_id: uuid.UUID
    credential: dict

    _size = field_validator("credential")(_limit_size)


class AuthenticationResultOut(BaseModel):
    verified: bool
    credential_id: uuid.UUID
    label: str | None
