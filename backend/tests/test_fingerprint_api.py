import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.biometrics.consent import CONSENT_VERSION
from app.config import settings
from app.core.roles import Role
from app.core.time import utcnow
from app.models import AuditLog, BiometricConsent, FaceTemplate, FingerprintCredential, WebAuthnChallenge
from tests.fakes import capture_set
from tests.helpers import auth_headers, make_org, make_user, org_admin
from tests.webauthn_fake import VirtualAuthenticator, b64, unb64

CONSENT = {"text_version": CONSENT_VERSION, "accepted": True, "given_by": "person", "signer_name": "Awa Diop"}


def new_person(client, headers, matricule="E1", first="Awa", last="Diop"):
    r = client.post("/persons", json={"matricule": matricule, "first_name": first, "last_name": last}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def consented(client, headers, **kw):
    pid = new_person(client, headers, **kw)
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers).status_code == 201
    return pid


def register(client, headers, pid, auth, label=None, **auth_kwargs):
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers)
    assert opts.status_code == 200, opts.text
    body = opts.json()
    credential = auth.register(body["options"], **auth_kwargs)
    return client.post(
        f"/persons/{pid}/fingerprint/register/verify",
        json={"challenge_id": body["challenge_id"], "credential": credential, "label": label},
        headers=headers,
    )


def auth_options(client, headers, pid):
    r = client.post(f"/persons/{pid}/fingerprint/authenticate/options", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def authenticate(client, headers, pid, auth, **auth_kwargs):
    body = auth_options(client, headers, pid)
    credential = auth.authenticate(body["options"], **auth_kwargs)
    return client.post(
        f"/persons/{pid}/fingerprint/authenticate/verify",
        json={"challenge_id": body["challenge_id"], "credential": credential},
        headers=headers,
    )


@pytest.fixture
def ctx(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    return client, db_session, org, headers


def actions(db):
    return [a for a in db.scalars(select(AuditLog.action))]


# ------------------------------------------------------------------ consentement

def test_fingerprint_needs_a_consent_of_the_current_version(ctx):
    client, db, org, headers = ctx
    pid = new_person(client, headers)
    url = f"/persons/{pid}/fingerprint/register/options"
    assert client.post(url, headers=headers).status_code == 409  # aucun consentement

    old = BiometricConsent(
        organisation_id=org.id, person_id=uuid.UUID(pid), text_version="v1", text_sha256="x" * 64,
        given_by="person", signer_name="Awa Diop",
    )
    db.add(old)
    db.commit()
    r = client.post(url, headers=headers)
    assert r.status_code == 409 and "renouvelle" in r.json()["detail"]
    info = client.get(f"/persons/{pid}/biometrics", headers=headers).json()
    assert info["consent_current"] is False and info["current_consent_version"] == CONSENT_VERSION

    # Le renouvellement remplace l'ancien consentement ; les visages déjà enrôlés sont conservés.
    assert client.post(f"/persons/{pid}/face/enroll", json={"images": capture_set()}, headers=headers).status_code == 201
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers).status_code == 201
    db.expire_all()
    assert db.get(BiometricConsent, old.id).revoked_at is not None
    assert len(db.scalars(select(FaceTemplate)).all()) == 5
    assert "consent.superseded" in actions(db)
    assert client.get(f"/persons/{pid}/biometrics", headers=headers).json()["consent_current"] is True
    assert client.post(url, headers=headers).status_code == 200


# ------------------------------------------------------------------ enregistrement

def test_registration_flow_keeps_only_the_public_key(ctx):
    client, db, org, headers = ctx
    pid = consented(client, headers)
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).json()["options"]
    assert opts["rp"]["id"] == "localhost"
    assert opts["authenticatorSelection"]["userVerification"] == "required"
    assert opts["authenticatorSelection"]["authenticatorAttachment"] == "platform"
    assert unb64(opts["user"]["id"]) == uuid.UUID(pid).bytes  # identifiant opaque
    assert opts["user"]["name"] == "E1" and opts["excludeCredentials"] == []

    auth = VirtualAuthenticator()
    r = register(client, headers, pid, auth, label="Index droit")
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "Index droit" and r.json()["provider"] == "webauthn"

    row = db.scalars(select(FingerprintCredential)).one()
    assert row.credential_id == b64(auth.credential_id) and row.sign_count == 0
    private_numbers = auth.key.private_numbers().private_value.to_bytes(32, "big")
    assert private_numbers not in row.public_key  # la clé privée ne quitte jamais l'appareil

    info = client.get(f"/persons/{pid}/biometrics", headers=headers).json()
    assert info["fingerprint"]["registered"] is True and info["fingerprint"]["credentials"][0]["label"] == "Index droit"
    assert client.get(f"/persons/{pid}", headers=headers).json()["fingerprint_enrolled"] is True
    assert "fingerprint.registered" in actions(db)


def test_default_label_and_exclusion_of_known_credentials(ctx):
    client, _, _, headers = ctx
    pid = consented(client, headers)
    first = VirtualAuthenticator()
    assert register(client, headers, pid, first).json()["label"]  # étiquette par défaut
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).json()["options"]
    assert [c["id"] for c in opts["excludeCredentials"]] == [b64(first.credential_id)]


def test_credentials_per_person_are_limited(ctx, monkeypatch):
    client, _, _, headers = ctx
    monkeypatch.setattr(settings, "max_fingerprints_per_person", 2)
    pid = consented(client, headers)
    for _ in range(2):
        assert register(client, headers, pid, VirtualAuthenticator()).status_code == 201
    assert client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).status_code == 409


def test_challenge_is_single_use_and_unknown_challenges_are_refused(ctx):
    client, _, _, headers = ctx
    pid = consented(client, headers)
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).json()
    auth = VirtualAuthenticator()
    payload = {"challenge_id": opts["challenge_id"], "credential": auth.register(opts["options"])}
    url = f"/persons/{pid}/fingerprint/register/verify"
    assert client.post(url, json=payload, headers=headers).status_code == 201
    assert client.post(url, json=payload, headers=headers).status_code == 400  # rejeu
    assert client.post(url, json={**payload, "challenge_id": str(uuid.uuid4())}, headers=headers).status_code == 400


def test_expired_challenge_is_refused(ctx):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).json()
    row = db.get(WebAuthnChallenge, uuid.UUID(opts["challenge_id"]))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    payload = {"challenge_id": opts["challenge_id"], "credential": VirtualAuthenticator().register(opts["options"])}
    r = client.post(f"/persons/{pid}/fingerprint/register/verify", json=payload, headers=headers)
    assert r.status_code == 400 and "expiré" in r.json()["detail"]


def test_challenge_is_bound_to_its_person_and_purpose(ctx):
    client, _, _, headers = ctx
    a = consented(client, headers, matricule="E1")
    b = consented(client, headers, matricule="E2", first="Moussa", last="Fall")
    opts = client.post(f"/persons/{a}/fingerprint/register/options", headers=headers).json()
    payload = {"challenge_id": opts["challenge_id"], "credential": VirtualAuthenticator().register(opts["options"])}
    assert client.post(f"/persons/{b}/fingerprint/register/verify", json=payload, headers=headers).status_code == 400

    # un défi « authentification » ne sert pas à enregistrer
    auth = VirtualAuthenticator()
    assert register(client, headers, a, auth).status_code == 201
    login = auth_options(client, headers, a)
    mixed = {"challenge_id": login["challenge_id"], "credential": VirtualAuthenticator().register(login["options"])}
    assert client.post(f"/persons/{a}/fingerprint/register/verify", json=mixed, headers=headers).status_code == 400


def test_registration_refuses_wrong_origin_and_missing_user_verification(ctx):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    evil = register(client, headers, pid, VirtualAuthenticator(), origin="http://evil.example")
    assert evil.status_code == 400 and "origin" in evil.json()["detail"].lower()
    no_uv = register(client, headers, pid, VirtualAuthenticator(user_verified=False))
    assert no_uv.status_code == 400
    wrong_rp = register(client, headers, pid, VirtualAuthenticator(rp_id="autre-site.example"))
    assert wrong_rp.status_code == 400
    assert db.scalars(select(FingerprintCredential)).all() == []
    assert register(client, headers, pid, VirtualAuthenticator()).status_code == 201  # une vraie tentative passe ensuite


def test_same_credential_cannot_be_registered_twice(ctx):
    client, _, _, headers = ctx
    a = consented(client, headers, matricule="E1")
    b = consented(client, headers, matricule="E2", first="Moussa", last="Fall")
    auth = VirtualAuthenticator()
    assert register(client, headers, a, auth).status_code == 201
    assert register(client, headers, b, auth).status_code == 409


# ------------------------------------------------------------------ vérification

def test_authentication_success_updates_counter_and_usage(ctx):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    auth = VirtualAuthenticator()
    register(client, headers, pid, auth)
    r = authenticate(client, headers, pid, auth)
    assert r.status_code == 200 and r.json()["verified"] is True
    row = db.scalars(select(FingerprintCredential)).one()
    db.refresh(row)
    assert row.sign_count == 1 and row.last_used_at is not None
    assert authenticate(client, headers, pid, auth).status_code == 200  # compteur 2 > 1
    assert "fingerprint.verified" in actions(db)


def test_authentication_options_only_offer_this_persons_credentials(ctx):
    client, _, _, headers = ctx
    a = consented(client, headers, matricule="E1")
    b = consented(client, headers, matricule="E2", first="Moussa", last="Fall")
    auth_a, auth_b = VirtualAuthenticator(), VirtualAuthenticator()
    register(client, headers, a, auth_a)
    register(client, headers, b, auth_b)
    allowed = [c["id"] for c in auth_options(client, headers, a)["options"]["allowCredentials"]]
    assert allowed == [b64(auth_a.credential_id)]
    assert auth_options(client, headers, a)["options"]["userVerification"] == "required"


def test_fingerprint_of_another_person_is_refused(ctx):
    client, db, _, headers = ctx
    a = consented(client, headers, matricule="E1")
    b = consented(client, headers, matricule="E2", first="Moussa", last="Fall")
    auth_a, auth_b = VirtualAuthenticator(), VirtualAuthenticator()
    register(client, headers, a, auth_a)
    register(client, headers, b, auth_b)
    # Moussa pose son doigt à la place d'Awa : sa clé n'est pas celle d'Awa.
    r = authenticate(client, headers, a, auth_b)
    assert r.status_code == 403
    assert "fingerprint.verify_failed" in actions(db)
    assert authenticate(client, headers, a, auth_a).status_code == 200


@pytest.mark.parametrize("kwargs", [{"tamper": True}, {"origin": "http://evil.example"}])
def test_forged_assertions_are_refused(ctx, kwargs):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    auth = VirtualAuthenticator()
    register(client, headers, pid, auth)
    assert authenticate(client, headers, pid, auth, **kwargs).status_code == 403
    assert "fingerprint.verify_failed" in actions(db)
    assert authenticate(client, headers, pid, auth).status_code == 200


def test_user_verification_is_required_for_authentication(ctx):
    client, _, _, headers = ctx
    pid = consented(client, headers)
    auth = VirtualAuthenticator()
    register(client, headers, pid, auth)
    auth.user_verified = False  # présence seule (ex. simple touche) : pas de doigt vérifié
    assert authenticate(client, headers, pid, auth).status_code == 403


def test_replayed_assertion_is_refused(ctx):
    client, _, _, headers = ctx
    pid = consented(client, headers)
    auth = VirtualAuthenticator()
    register(client, headers, pid, auth)
    body = auth_options(client, headers, pid)
    payload = {"challenge_id": body["challenge_id"], "credential": auth.authenticate(body["options"])}
    url = f"/persons/{pid}/fingerprint/authenticate/verify"
    assert client.post(url, json=payload, headers=headers).status_code == 200
    assert client.post(url, json=payload, headers=headers).status_code == 400


def test_counter_regression_signals_a_cloned_authenticator(ctx):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    auth = VirtualAuthenticator(counter_start=10)
    register(client, headers, pid, auth)
    assert authenticate(client, headers, pid, auth).status_code == 200  # compteur 11
    auth.sign_count = 3  # un « clone » repart d'un compteur plus bas
    assert authenticate(client, headers, pid, auth, bump=False).status_code == 403
    assert "fingerprint.counter_regression" in actions(db)


def test_authenticators_that_keep_the_counter_at_zero_still_work(ctx):
    """Windows Hello renvoie souvent toujours 0 : ce n'est pas une anomalie."""
    client, _, _, headers = ctx
    pid = consented(client, headers)
    auth = VirtualAuthenticator()
    register(client, headers, pid, auth)
    assert authenticate(client, headers, pid, auth, bump=False).status_code == 200
    assert authenticate(client, headers, pid, auth, bump=False).status_code == 200


def test_authentication_needs_a_registered_fingerprint(ctx):
    client, _, _, headers = ctx
    pid = consented(client, headers)
    assert client.post(f"/persons/{pid}/fingerprint/authenticate/options", headers=headers).status_code == 409


# ------------------------------------------------------------------ suppression

def test_delete_one_credential(ctx):
    client, db, _, headers = ctx
    a = consented(client, headers, matricule="E1")
    b = consented(client, headers, matricule="E2", first="Moussa", last="Fall")
    register(client, headers, a, VirtualAuthenticator())
    register(client, headers, b, VirtualAuthenticator())
    cred_a = client.get(f"/persons/{a}/biometrics", headers=headers).json()["fingerprint"]["credentials"][0]["id"]

    assert client.delete(f"/persons/{b}/fingerprint/{cred_a}", headers=headers).status_code == 404  # pas la sienne
    assert client.delete(f"/persons/{a}/fingerprint/{cred_a}", headers=headers).status_code == 204
    assert client.delete(f"/persons/{a}/fingerprint/{cred_a}", headers=headers).status_code == 404
    assert client.get(f"/persons/{a}", headers=headers).json()["fingerprint_enrolled"] is False
    assert client.get(f"/persons/{b}", headers=headers).json()["fingerprint_enrolled"] is True
    assert "fingerprint.deleted" in actions(db)


def test_revoking_consent_deletes_face_and_fingerprint_data(ctx):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    client.post(f"/persons/{pid}/face/enroll", json={"images": capture_set()}, headers=headers)
    register(client, headers, pid, VirtualAuthenticator())
    assert client.delete(f"/persons/{pid}/consent", headers=headers).status_code == 204
    assert db.scalars(select(FingerprintCredential)).all() == []
    assert db.scalars(select(FaceTemplate)).all() == []
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "consent.revoked")).one()
    assert entry.details["fingerprints_deleted"] == 1 and entry.details["templates_deleted"] == 5


def test_deleting_a_person_deletes_their_fingerprints(ctx):
    client, db, _, headers = ctx
    pid = consented(client, headers)
    register(client, headers, pid, VirtualAuthenticator())
    assert client.delete(f"/persons/{pid}", headers=headers).status_code == 204
    assert db.scalars(select(FingerprintCredential)).all() == []
    assert db.scalars(select(WebAuthnChallenge)).all() == []


# ------------------------------------------------------------------ droits et isolation

def test_permissions(ctx, db_session):
    client, _, org, admin = ctx
    pid = consented(client, admin)
    register(client, admin, pid, VirtualAuthenticator())
    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    make_user(db_session, "emp@ecole.sn", Role.PERSONNE, org)
    manager, employee = auth_headers(client, "chef@ecole.sn"), auth_headers(client, "emp@ecole.sn")

    summary = client.get(f"/persons/{pid}/biometrics", headers=manager).json()["fingerprint"]
    assert summary["registered"] is True
    assert client.post(f"/persons/{pid}/fingerprint/register/options", headers=manager).status_code == 403
    assert client.post(f"/persons/{pid}/fingerprint/authenticate/options", headers=manager).status_code == 403
    assert client.delete(f"/persons/{pid}/fingerprint/{summary['credentials'][0]['id']}", headers=manager).status_code == 403
    assert client.post(f"/persons/{pid}/fingerprint/register/options", headers=employee).status_code == 403
    assert client.post(f"/persons/{pid}/fingerprint/register/options").status_code == 401


def test_other_organisation_cannot_touch_fingerprints(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    pid = consented(client, headers_a)
    register(client, headers_a, pid, VirtualAuthenticator())
    cred = client.get(f"/persons/{pid}/biometrics", headers=headers_a).json()["fingerprint"]["credentials"][0]["id"]

    for path in ("register/options", "authenticate/options"):
        assert client.post(f"/persons/{pid}/fingerprint/{path}", headers=headers_b).status_code == 404
    payload = {"challenge_id": str(uuid.uuid4()), "credential": {}}
    assert client.post(f"/persons/{pid}/fingerprint/register/verify", json=payload, headers=headers_b).status_code == 404
    assert client.post(f"/persons/{pid}/fingerprint/authenticate/verify", json=payload, headers=headers_b).status_code == 404
    assert client.delete(f"/persons/{pid}/fingerprint/{cred}", headers=headers_b).status_code == 404


def test_super_admin_must_name_the_organisation(client, db_session):
    org = make_org(db_session)
    admin = org_admin(client, db_session, org)
    pid = consented(client, admin)
    make_user(db_session, "root@pointage.sn", Role.SUPER_ADMIN)
    root = auth_headers(client, "root@pointage.sn")
    assert client.post(f"/persons/{pid}/fingerprint/register/options", headers=root).status_code == 422
    scoped = {**root, "X-Organisation-Id": str(org.id)}
    assert client.post(f"/persons/{pid}/fingerprint/register/options", headers=scoped).status_code == 200


def test_oversized_credential_payload_is_refused(ctx):
    client, _, _, headers = ctx
    pid = consented(client, headers)
    opts = client.post(f"/persons/{pid}/fingerprint/register/options", headers=headers).json()
    big = {"id": "x" * 40_000}
    r = client.post(f"/persons/{pid}/fingerprint/register/verify", json={"challenge_id": opts["challenge_id"], "credential": big}, headers=headers)
    assert r.status_code == 422


def test_origins_setting_accepts_several_origins(monkeypatch):
    monkeypatch.setattr(settings, "webauthn_origins", "http://localhost:3000, https://pointage.exemple.sn")
    assert settings.webauthn_origins_list == ["http://localhost:3000", "https://pointage.exemple.sn"]
