"""Chiffrement des gabarits biométriques (AES-256-GCM).

Format d'un gabarit stocké : 1 octet de version | 12 octets de nonce | données chiffrées + tag.
Les « données associées » (AAD) lient chaque gabarit à son organisation, sa personne et sa pose :
copier un gabarit chiffré d'une personne vers une autre le rend illisible.
"""
import base64
import os
import uuid

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

FORMAT_VERSION = 1


class CryptoNotConfigured(RuntimeError):
    pass


class DecryptionError(RuntimeError):
    pass


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _key() -> bytes:
    raw = settings.face_encryption_key.strip()
    if not raw:
        raise CryptoNotConfigured("FACE_ENCRYPTION_KEY n'est pas définie")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise CryptoNotConfigured("FACE_ENCRYPTION_KEY n'est pas du base64 valide") from exc
    if len(key) != 32:
        raise CryptoNotConfigured("FACE_ENCRYPTION_KEY doit faire exactement 32 octets")
    return key


def ensure_configured() -> None:
    _key()


def template_aad(org_id: uuid.UUID, person_id: uuid.UUID, pose: str) -> bytes:
    return f"{org_id}:{person_id}:{pose}".encode()


def encrypt_embedding(vector: np.ndarray, aad: bytes) -> bytes:
    data = np.asarray(vector, dtype=np.float32).tobytes()
    nonce = os.urandom(12)
    return bytes([FORMAT_VERSION]) + nonce + AESGCM(_key()).encrypt(nonce, data, aad)


def decrypt_embedding(blob: bytes, aad: bytes) -> np.ndarray:
    if len(blob) < 1 + 12 + 16 or blob[0] != FORMAT_VERSION:
        raise DecryptionError("Format de gabarit inconnu")
    try:
        data = AESGCM(_key()).decrypt(blob[1:13], blob[13:], aad)
    except InvalidTag as exc:
        raise DecryptionError("Gabarit illisible : clé modifiée ou données altérées") from exc
    return np.frombuffer(data, dtype=np.float32).copy()
