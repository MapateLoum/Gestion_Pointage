"""Contrat d'un « fournisseur d'empreinte ». Le reste du code ne dépend que de lui, ce qui permet
de brancher plus tard un lecteur USB (ZKTeco, SecuGen...) sans toucher au pointage.

Fournisseur actuel : « webauthn » (Windows Hello, Touch ID, lecteur intégré du PC).
Fournisseur prévu  : « usb » (agent local + lecteur dédié, pour les déploiements à plusieurs bornes).
"""
import uuid
from typing import Protocol

from sqlalchemy.orm import Session

from app.models import FingerprintCredential, Person


class FingerprintProvider(Protocol):
    name: str

    def begin_registration(self, db: Session, person: Person) -> tuple[uuid.UUID, dict]: ...

    def finish_registration(
        self, db: Session, person: Person, challenge_id: uuid.UUID, credential: dict, label: str | None
    ) -> FingerprintCredential: ...

    def begin_authentication(self, db: Session, person: Person) -> tuple[uuid.UUID, dict]: ...

    def finish_authentication(
        self, db: Session, person: Person, challenge_id: uuid.UUID, credential: dict
    ) -> FingerprintCredential: ...
