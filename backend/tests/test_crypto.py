import uuid

import numpy as np
import pytest

from app.config import settings
from app.core import crypto


def vector():
    v = np.random.default_rng(7).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def test_round_trip_and_randomised_nonce():
    org, person = uuid.uuid4(), uuid.uuid4()
    aad = crypto.template_aad(org, person, "front")
    a = crypto.encrypt_embedding(vector(), aad)
    b = crypto.encrypt_embedding(vector(), aad)
    assert a != b  # nonce différent à chaque chiffrement
    assert np.allclose(crypto.decrypt_embedding(a, aad), vector())
    assert vector().tobytes() not in a  # le vecteur n'apparaît jamais en clair


def test_template_is_bound_to_its_owner_and_pose():
    org, person = uuid.uuid4(), uuid.uuid4()
    blob = crypto.encrypt_embedding(vector(), crypto.template_aad(org, person, "front"))
    for aad in (
        crypto.template_aad(org, uuid.uuid4(), "front"),  # copié vers une autre personne
        crypto.template_aad(uuid.uuid4(), person, "front"),  # autre organisation
        crypto.template_aad(org, person, "left"),  # autre pose
    ):
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt_embedding(blob, aad)


def test_tampering_is_detected():
    aad = b"x"
    blob = bytearray(crypto.encrypt_embedding(vector(), aad))
    blob[20] ^= 0x01
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_embedding(bytes(blob), aad)
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_embedding(b"court", aad)


def test_wrong_key_cannot_decrypt(monkeypatch):
    blob = crypto.encrypt_embedding(vector(), b"x")
    monkeypatch.setattr(settings, "face_encryption_key", crypto.generate_key())
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_embedding(blob, b"x")


@pytest.mark.parametrize("bad", ["", "pas-du-base64!!", "AAAA"])
def test_missing_or_invalid_key(monkeypatch, bad):
    monkeypatch.setattr(settings, "face_encryption_key", bad)
    with pytest.raises(crypto.CryptoNotConfigured):
        crypto.encrypt_embedding(vector(), b"x")


def test_generated_key_is_valid(monkeypatch):
    monkeypatch.setattr(settings, "face_encryption_key", crypto.generate_key())
    crypto.ensure_configured()
