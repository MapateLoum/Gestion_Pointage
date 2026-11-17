import pytest
from sqlalchemy import select

from app.config import settings
from app.core import crypto
from app.core.roles import Role
from app.models import AuditLog, FaceTemplate, Person
from app.biometrics.consent import CONSENT_VERSION
from tests.fakes import FakeEngine, capture_set, embedding_for, make_image
from tests.helpers import auth_headers, make_org, make_user, org_admin

CONSENT = {"text_version": CONSENT_VERSION, "accepted": True, "given_by": "person", "signer_name": "Awa Diop"}


def new_person(client, headers, matricule="E1", first="Awa", last="Diop"):
    r = client.post("/persons", json={"matricule": matricule, "first_name": first, "last_name": last}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def consented_person(client, headers, **kwargs):
    pid = new_person(client, headers, **kwargs)
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers).status_code == 201
    return pid


@pytest.fixture
def ctx(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    return client, db_session, org, headers


def enroll(client, headers, pid, images=None):
    return client.post(f"/persons/{pid}/face/enroll", json={"images": images or capture_set()}, headers=headers)


# ------------------------------------------------------------------ état et consentement

def test_engine_status(ctx):
    client, _, _, headers = ctx
    body = client.get("/face/status", headers=headers).json()
    assert body["ready"] is True and body["encryption_configured"] is True


def test_status_reports_missing_encryption_key(ctx, monkeypatch):
    client, _, _, headers = ctx
    monkeypatch.setattr(settings, "face_encryption_key", "")
    assert client.get("/face/status", headers=headers).json()["encryption_configured"] is False


def test_consent_flow(ctx):
    client, db, org, headers = ctx
    pid = new_person(client, headers)

    text = client.get(f"/persons/{pid}/consent-text", headers=headers).json()
    assert text["version"] == CONSENT_VERSION and org.name in text["text"]

    assert client.post(f"/persons/{pid}/consent", json={**CONSENT, "text_version": "v0"}, headers=headers).status_code == 422
    assert client.post(f"/persons/{pid}/consent", json={**CONSENT, "accepted": False}, headers=headers).status_code == 422
    assert client.post(f"/persons/{pid}/consent", json={**CONSENT, "signer_name": "A"}, headers=headers).status_code == 422

    created = client.post(f"/persons/{pid}/consent", json={**CONSENT, "given_by": "guardian"}, headers=headers)
    assert created.status_code == 201 and created.json()["given_by"] == "guardian"
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers).status_code == 409

    info = client.get(f"/persons/{pid}/biometrics", headers=headers).json()
    assert info["consent"]["signer_name"] == "Awa Diop" and info["face"]["enrolled"] is False
    person = client.get(f"/persons/{pid}", headers=headers).json()
    assert person["consent_active"] is True and person["face_enrolled"] is False
    assert "consent.recorded" in set(db.scalars(select(AuditLog.action)))


def test_captures_require_consent(ctx):
    client, _, _, headers = ctx
    pid = new_person(client, headers)
    analyze = {"image": make_image(), "pose": "front"}
    assert client.post(f"/persons/{pid}/face/analyze", json=analyze, headers=headers).status_code == 409
    assert enroll(client, headers, pid).status_code == 409


# ------------------------------------------------------------------ analyse en direct

@pytest.mark.parametrize(
    "kind, code",
    [("noface", "no_face"), ("two", "multiple_faces"), ("small", "too_small"), ("cutoff", "cut_off"),
     ("dark", "too_dark"), ("blurry", "blurry")],
)
def test_analyze_reports_quality_problems(ctx, kind, code):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    body = client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(kind=kind), "pose": "front"}, headers=headers).json()
    assert body["ok"] is False
    assert code in [i["code"] for i in body["issues"]]
    assert all(i["message"] for i in body["issues"])


def test_analyze_accepts_a_good_frame_and_returns_angles(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    body = client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(yaw=3, pitch=-2), "pose": "front"}, headers=headers).json()
    assert body["ok"] is True and body["issues"] == []
    assert body["pose"]["yaw"] == pytest.approx(3, abs=2) and body["pose"]["pitch"] == pytest.approx(-2, abs=2)
    assert body["metrics"]["sharpness"] > settings.face_min_sharpness


def test_analyze_checks_the_requested_pose_against_the_front_pose(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)

    def analyze(pose, yaw=0, pitch=0, reference=None):
        payload = {"image": make_image(yaw=yaw, pitch=pitch), "pose": pose}
        if reference:
            payload["reference"] = reference
        r = client.post(f"/persons/{pid}/face/analyze", json=payload, headers=headers)
        return r.json()

    ref = {"yaw": 0, "pitch": 0, "roll": 0}
    assert analyze("left", yaw=-25)["issues"][0]["code"] == "no_reference"
    assert analyze("left", yaw=-25, reference=ref)["ok"] is True
    assert analyze("left", yaw=-5, reference=ref)["issues"][0]["code"] == "turn_more"
    assert analyze("up", pitch=-15, reference=ref)["ok"] is True
    assert analyze("down", pitch=2, reference=ref)["issues"][0]["code"] == "tilt_more"
    assert analyze("front", yaw=40)["issues"][0]["code"] == "not_frontal"


def test_analyze_rejects_garbage_images(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    url = f"/persons/{pid}/face/analyze"
    long_text = "x" * 200
    assert client.post(url, json={"image": long_text, "pose": "front"}, headers=headers).status_code == 422
    import base64

    junk = base64.b64encode(b"ceci n'est pas une image" * 20).decode()
    assert client.post(url, json={"image": junk, "pose": "front"}, headers=headers).status_code == 422
    assert client.post(url, json={"image": make_image(), "pose": "diagonale"}, headers=headers).status_code == 422


def test_engine_not_ready_gives_a_clear_503(ctx, face_engine):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    face_engine.ready = False
    r = client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(), "pose": "front"}, headers=headers)
    assert r.status_code == 503 and "charge" in r.json()["detail"]
    assert enroll(client, headers, pid).status_code == 503


# ------------------------------------------------------------------ enrôlement

def test_enrollment_stores_only_encrypted_templates(ctx):
    client, db, org, headers = ctx
    pid = consented_person(client, headers)
    r = enroll(client, headers, pid)
    assert r.status_code == 201
    assert r.json()["templates"] == 5 and sorted(r.json()["poses"]) == ["down", "front", "left", "right", "up"]

    templates = list(db.scalars(select(FaceTemplate)))
    assert {t.pose for t in templates} == {"front", "left", "right", "up", "down"}
    front = next(t for t in templates if t.pose == "front")
    plain = embedding_for(1, 0, 0)
    assert plain.tobytes() not in front.embedding  # jamais en clair
    decrypted = crypto.decrypt_embedding(front.embedding, crypto.template_aad(org.id, front.person_id, "front"))
    assert float(decrypted @ plain) > 0.99  # mais bien exploitable avec la clé

    info = client.get(f"/persons/{pid}/biometrics", headers=headers).json()
    assert info["face"]["enrolled"] is True and info["face"]["templates"] == 5
    assert client.get(f"/persons/{pid}", headers=headers).json()["face_enrolled"] is True
    listed = client.get("/persons", headers=headers).json()["items"][0]
    assert listed["face_enrolled"] is True and listed["consent_active"] is True
    assert "face.enrolled" in set(db.scalars(select(AuditLog.action)))


def test_reenrollment_replaces_previous_templates(ctx):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    assert enroll(client, headers, pid).status_code == 201
    old_ids = set(db.scalars(select(FaceTemplate.id)))
    assert enroll(client, headers, pid).status_code == 201
    new_ids = set(db.scalars(select(FaceTemplate.id)))
    assert len(new_ids) == 5 and not (old_ids & new_ids)


def test_duplicate_face_is_rejected_and_nothing_is_stored(ctx):
    client, db, _, headers = ctx
    first = consented_person(client, headers, matricule="E1", first="Awa", last="Diop")
    assert enroll(client, headers, first, capture_set(identity=1)).status_code == 201

    second = consented_person(client, headers, matricule="E2", first="Moussa", last="Fall")
    r = enroll(client, headers, second, capture_set(identity=1))  # même visage, autre fiche
    assert r.status_code == 409
    assert "Awa Diop" in r.json()["detail"] and r.json()["duplicate"]["matricule"] == "E1"
    assert db.scalars(select(FaceTemplate).where(FaceTemplate.person_id == __import__("uuid").UUID(second))).all() == []
    assert "face.duplicate_rejected" in set(db.scalars(select(AuditLog.action)))

    assert enroll(client, headers, second, capture_set(identity=2)).status_code == 201  # visage différent : accepté


def test_re_enrolling_the_same_person_is_not_a_duplicate(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    assert enroll(client, headers, pid, capture_set(identity=1)).status_code == 201
    assert enroll(client, headers, pid, capture_set(identity=1)).status_code == 201


def test_same_face_in_another_organisation_is_allowed(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    pa = consented_person(client, headers_a)
    pb = consented_person(client, headers_b)
    assert enroll(client, headers_a, pa, capture_set(identity=1)).status_code == 201
    assert enroll(client, headers_b, pb, capture_set(identity=1)).status_code == 201  # isolation entre clients


def test_captures_of_different_people_are_rejected(ctx):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    images = capture_set(identity=1, left={"identity": 2})
    r = enroll(client, headers, pid, images)
    assert r.status_code == 422
    assert [i["code"] for i in r.json()["poses"]["left"]] == ["different_person"]
    assert db.scalars(select(FaceTemplate)).all() == []


def test_bad_captures_are_reported_per_pose(ctx):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    r = enroll(client, headers, pid, capture_set(up={"kind": "blurry"}, down={"kind": "dark"}))
    assert r.status_code == 422
    poses = r.json()["poses"]
    assert "blurry" in [i["code"] for i in poses["up"]] and "too_dark" in [i["code"] for i in poses["down"]]
    assert db.scalars(select(FaceTemplate)).all() == []


def test_bad_front_pose_blocks_enrollment(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    r = enroll(client, headers, pid, capture_set(front={"yaw": 40}))
    assert r.status_code == 422 and r.json()["poses"]["front"][0]["code"] == "not_frontal"


def test_same_direction_twice_is_rejected(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    r = enroll(client, headers, pid, capture_set(right={"yaw": -25}))
    assert r.status_code == 422 and r.json()["poses"]["right"][0]["code"] == "same_direction"


def test_pose_checks_can_be_disabled(ctx, monkeypatch):
    client, _, _, headers = ctx
    monkeypatch.setattr(settings, "face_enforce_poses", False)
    pid = consented_person(client, headers)
    flat = capture_set(left={"yaw": 0}, right={"yaw": 0}, up={"pitch": 0}, down={"pitch": 0})
    assert enroll(client, headers, pid, flat).status_code == 201


def test_exactly_five_distinct_poses_are_required(ctx):
    client, _, _, headers = ctx
    pid = consented_person(client, headers)
    images = capture_set()
    assert enroll(client, headers, pid, images[:4]).status_code == 422
    duplicated = images[:4] + [images[0]]
    assert enroll(client, headers, pid, duplicated).status_code == 422


def test_enrollment_needs_the_encryption_key(ctx, monkeypatch):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    monkeypatch.setattr(settings, "face_encryption_key", "")
    r = enroll(client, headers, pid)
    assert r.status_code == 503 and "FACE_ENCRYPTION_KEY" in r.json()["detail"]
    assert db.scalars(select(FaceTemplate)).all() == []


def test_unreadable_existing_templates_give_a_clear_error(ctx, monkeypatch):
    client, _, _, headers = ctx
    first = consented_person(client, headers, matricule="E1")
    assert enroll(client, headers, first, capture_set(identity=1)).status_code == 201
    second = consented_person(client, headers, matricule="E2", first="Moussa", last="Fall")
    monkeypatch.setattr(settings, "face_encryption_key", crypto.generate_key())  # la clé a changé
    r = enroll(client, headers, second, capture_set(identity=2))
    assert r.status_code == 503 and "clé" in r.json()["detail"]


# ------------------------------------------------------------------ retrait et suppression

def test_revoking_consent_deletes_face_data(ctx):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    enroll(client, headers, pid)

    assert client.delete(f"/persons/{pid}/consent", headers=headers).status_code == 204
    assert db.scalars(select(FaceTemplate)).all() == []
    info = client.get(f"/persons/{pid}/biometrics", headers=headers).json()
    assert info["consent"] is None and info["face"]["enrolled"] is False
    assert client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(), "pose": "front"}, headers=headers).status_code == 409
    assert client.delete(f"/persons/{pid}/consent", headers=headers).status_code == 404

    entry = db.scalars(select(AuditLog).where(AuditLog.action == "consent.revoked")).one()
    assert entry.details["templates_deleted"] == 5

    # on peut ensuite redonner son consentement
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers).status_code == 201


def test_delete_face_data(ctx):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    assert client.delete(f"/persons/{pid}/face", headers=headers).status_code == 404
    enroll(client, headers, pid)
    assert client.delete(f"/persons/{pid}/face", headers=headers).status_code == 204
    assert db.scalars(select(FaceTemplate)).all() == []
    assert "face.deleted" in set(db.scalars(select(AuditLog.action)))
    assert client.get(f"/persons/{pid}/biometrics", headers=headers).json()["consent"] is not None  # le consentement reste


def test_deleting_a_person_deletes_their_biometrics(ctx):
    client, db, _, headers = ctx
    pid = consented_person(client, headers)
    enroll(client, headers, pid)
    assert client.delete(f"/persons/{pid}", headers=headers).status_code == 204
    assert db.scalars(select(FaceTemplate)).all() == []


# ------------------------------------------------------------------ droits et isolation

def test_permissions(ctx, db_session):
    client, _, org, admin = ctx
    pid = consented_person(client, admin)
    enroll(client, admin, pid)
    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    make_user(db_session, "emp@ecole.sn", Role.PERSONNE, org)
    manager, employee = auth_headers(client, "chef@ecole.sn"), auth_headers(client, "emp@ecole.sn")

    assert client.get(f"/persons/{pid}/biometrics", headers=manager).status_code == 200
    assert client.get("/face/status", headers=manager).status_code == 200
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=manager).status_code == 403
    assert client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(), "pose": "front"}, headers=manager).status_code == 403
    assert enroll(client, manager, pid).status_code == 403
    assert client.delete(f"/persons/{pid}/face", headers=manager).status_code == 403
    assert client.get(f"/persons/{pid}/biometrics", headers=employee).status_code == 403
    assert client.get(f"/persons/{pid}/biometrics").status_code == 401


def test_other_organisation_cannot_touch_biometrics(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    pid = consented_person(client, headers_a)
    enroll(client, headers_a, pid)

    analyze = {"image": make_image(), "pose": "front"}
    assert client.get(f"/persons/{pid}/biometrics", headers=headers_b).status_code == 404
    assert client.get(f"/persons/{pid}/consent-text", headers=headers_b).status_code == 404
    assert client.post(f"/persons/{pid}/consent", json=CONSENT, headers=headers_b).status_code == 404
    assert client.post(f"/persons/{pid}/face/analyze", json=analyze, headers=headers_b).status_code == 404
    assert enroll(client, headers_b, pid).status_code == 404
    assert client.delete(f"/persons/{pid}/face", headers=headers_b).status_code == 404
    assert client.delete(f"/persons/{pid}/consent", headers=headers_b).status_code == 404


def test_super_admin_must_name_the_organisation(client, db_session):
    org = make_org(db_session)
    admin = org_admin(client, db_session, org)
    pid = consented_person(client, admin)
    make_user(db_session, "root@pointage.sn", Role.SUPER_ADMIN)
    root = auth_headers(client, "root@pointage.sn")
    assert client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(), "pose": "front"}, headers=root).status_code == 422
    scoped = {**root, "X-Organisation-Id": str(org.id)}
    assert client.post(f"/persons/{pid}/face/analyze", json={"image": make_image(), "pose": "front"}, headers=scoped).status_code == 200
