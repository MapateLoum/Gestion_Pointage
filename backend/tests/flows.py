"""Scénarios réutilisés par plusieurs fichiers de tests."""
from app.biometrics.consent import CONSENT_VERSION
from tests.fakes import capture_set
from tests.webauthn_fake import VirtualAuthenticator

CONSENT = {"text_version": CONSENT_VERSION, "accepted": True, "given_by": "person", "signer_name": "Awa Diop"}


def new_person(client, headers, matricule="E1", first="Awa", last="Diop", **extra):
    r = client.post("/persons", json={"matricule": matricule, "first_name": first, "last_name": last, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def register_fingerprint(client, headers, pid, auth, label=None):
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).json()
    credential = auth.register(opts["options"])
    r = client.post(
        f"/persons/{pid}/fingerprint/register/verify",
        json={"challenge_id": opts["challenge_id"], "credential": credential, "label": label},
        headers=headers,
    )
    assert r.status_code == 201, r.text


def enrolled_person(client, headers, identity=1, matricule="E1", first="Awa", last="Diop", fingerprint=True, **extra):
    """Personne avec consentement, visage enrôlé et (par défaut) une empreinte. Renvoie (id, authentificateur)."""
    pid = new_person(client, headers, matricule, first, last, **extra)
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers).status_code == 201
    r = client.post(f"/persons/{pid}/face/enroll", json={"images": capture_set(identity=identity)}, headers=headers)
    assert r.status_code == 201, r.text
    auth = VirtualAuthenticator()
    if fingerprint:
        register_fingerprint(client, headers, pid, auth)
    return pid, auth


def make_terminal(client, headers, name="Borne 1", **payload):
    r = client.post("/terminals", json={"name": name, **payload}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
