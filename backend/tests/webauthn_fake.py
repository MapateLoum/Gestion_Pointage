"""Authentificateur WebAuthn virtuel pour les tests : il fait ce que ferait Windows Hello
(créer une clé, signer un défi) sans aucun matériel."""
import base64
import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, AT = 0x01, 0x04, 0x40


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class VirtualAuthenticator:
    def __init__(self, rp_id="localhost", origin="http://localhost:3000", user_verified=True, counter_start=0):
        self.rp_id, self.origin, self.user_verified = rp_id, origin, user_verified
        self.sign_count = counter_start
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)

    @property
    def rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def _flags(self, attested: bool) -> int:
        return UP | (UV if self.user_verified else 0) | (AT if attested else 0)

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}
        ).encode()

    def register(self, options: dict, origin: str | None = None) -> dict:
        """Équivalent de navigator.credentials.create(...)."""
        auth_data = (
            self.rp_hash
            + bytes([self._flags(attested=True)])
            + self.sign_count.to_bytes(4, "big")
            + bytes(16)  # AAGUID
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + self._cose_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "attestationObject": b64(attestation),
                "clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
                "transports": ["internal"],
            },
        }

    def authenticate(self, options: dict, origin: str | None = None, bump: bool = True, tamper: bool = False) -> dict:
        """Équivalent de navigator.credentials.get(...)."""
        if bump:
            self.sign_count += 1
        auth_data = self.rp_hash + bytes([self._flags(attested=False)]) + self.sign_count.to_bytes(4, "big")
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        if tamper:
            signature = signature[:-1] + bytes([signature[-1] ^ 1])
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "authenticatorData": b64(auth_data),
                "clientDataJSON": b64(client_data),
                "signature": b64(signature),
                "userHandle": options.get("user_handle", ""),
            },
        }
