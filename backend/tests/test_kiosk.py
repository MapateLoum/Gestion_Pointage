import uuid
from datetime import timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.biometrics.face import gallery
from app.biometrics.face.liveness import STEPS
from app.config import settings
from app.core.roles import Role
from app.core.time import utcnow
from app.models import AttendanceAttempt, AttendanceRecord, Person, Terminal
from tests.fakes import liveness_frames, make_image
from tests.flows import enrolled_person, make_terminal, new_person
from tests.helpers import auth_headers, make_org, make_user, org_admin
from tests.webauthn_fake import VirtualAuthenticator


def H(key):
    return {"X-Terminal-Key": key}


@pytest.fixture(autouse=True)
def fresh_gallery():
    gallery.clear_cache()


@pytest.fixture
def ctx(client, db_session):
    org = make_org(db_session)
    admin = org_admin(client, db_session, org)
    terminal = make_terminal(client, admin)
    return client, db_session, org, admin, terminal


def challenge(client, key):
    r = client.post("/kiosk/challenges", headers=H(key))
    assert r.status_code == 200, r.text
    return r.json()


def attempt(client, key, frames_for, **kw):
    """Un pointage complet jusqu'à la réponse du serveur (avant l'empreinte)."""
    ch = challenge(client, key)
    frames = frames_for(ch["steps"]) if callable(frames_for) else frames_for
    r = client.post("/kiosk/attempts", json={"challenge_id": ch["challenge_id"], "frames": frames}, headers=H(key))
    return r


def good(identity=1, **kw):
    return lambda steps: liveness_frames(steps, identity, **kw)


def clock_in(client, key, auth, identity=1):
    """Visage + empreinte : renvoie la réponse finale."""
    first = attempt(client, key, good(identity)).json()
    assert first["status"] == "pending_fingerprint", first
    credential = auth.authenticate(first["webauthn"]["options"])
    return client.post(f"/kiosk/attempts/{first['attempt_id']}/fingerprint", json={"credential": credential}, headers=H(key))


# ------------------------------------------------------------------ terminaux

def test_terminal_key_is_shown_once_and_only_its_hash_is_stored(ctx):
    client, db, _, admin, terminal = ctx
    assert terminal["key"].startswith("trm_") and terminal["key_prefix"] == terminal["key"][:8]
    row = db.scalars(select(Terminal)).one()
    assert terminal["key"] not in (row.key_hash, row.key_prefix) and len(row.key_hash) == 64
    listed = client.get("/terminals", headers=admin).json()
    assert len(listed) == 1 and "key" not in listed[0]


def test_terminal_management_rules(ctx, db_session):
    client, _, org, admin, terminal = ctx
    assert client.post("/terminals", json={"name": "Borne 1"}, headers=admin).status_code == 409
    other_org = make_org(db_session, "Autre")
    other_admin = org_admin(client, db_session, other_org, "b@x.sn")
    foreign_site = client.post("/sites", json={"name": "Site B"}, headers=other_admin).json()
    assert client.post("/terminals", json={"name": "Borne 2", "site_id": foreign_site["id"]}, headers=admin).status_code == 422

    site = client.post("/sites", json={"name": "Siège"}, headers=admin).json()
    patched = client.patch(f"/terminals/{terminal['id']}", json={"site_id": site["id"], "fingerprint_required": False}, headers=admin)
    assert patched.status_code == 200 and patched.json()["fingerprint_required"] is False
    assert client.patch(f"/terminals/{terminal['id']}", json={"name": None}, headers=admin).status_code == 422
    assert client.delete(f"/terminals/{terminal['id']}", headers=admin).status_code == 204
    assert client.get("/terminals", headers=admin).json() == []


def test_rotating_the_key_cuts_the_old_one(ctx):
    client, _, _, admin, terminal = ctx
    assert client.get("/kiosk/me", headers=H(terminal["key"])).status_code == 200
    rotated = client.post(f"/terminals/{terminal['id']}/rotate-key", headers=admin).json()
    assert rotated["key"] != terminal["key"]
    assert client.get("/kiosk/me", headers=H(terminal["key"])).status_code == 401
    assert client.get("/kiosk/me", headers=H(rotated["key"])).status_code == 200


def test_terminal_admin_permissions_and_isolation(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    admin_a = org_admin(client, db_session, org_a, "a@x.sn")
    admin_b = org_admin(client, db_session, org_b, "b@x.sn")
    terminal = make_terminal(client, admin_a)
    make_user(db_session, "chef@x.sn", Role.MANAGER, org_a)
    make_user(db_session, "emp@x.sn", Role.PERSONNE, org_a)
    manager, employee = auth_headers(client, "chef@x.sn"), auth_headers(client, "emp@x.sn")

    assert len(client.get("/terminals", headers=manager).json()) == 1
    assert client.post("/terminals", json={"name": "X1"}, headers=manager).status_code == 403
    assert client.post(f"/terminals/{terminal['id']}/rotate-key", headers=manager).status_code == 403
    assert client.get("/terminals", headers=employee).status_code == 403

    assert client.get("/terminals", headers=admin_b).json() == []
    assert client.patch(f"/terminals/{terminal['id']}", json={"name": "Piraté"}, headers=admin_b).status_code == 404
    assert client.post(f"/terminals/{terminal['id']}/rotate-key", headers=admin_b).status_code == 404
    assert client.delete(f"/terminals/{terminal['id']}", headers=admin_b).status_code == 404

    make_user(db_session, "root@x.sn", Role.SUPER_ADMIN)
    root = auth_headers(client, "root@x.sn")
    assert client.post("/terminals", json={"name": "X2"}, headers=root).status_code == 422


def test_kiosk_authentication(ctx, db_session):
    client, db, _, admin, terminal = ctx
    assert client.get("/kiosk/me").status_code == 401
    assert client.get("/kiosk/me", headers=H("trm_faux")).status_code == 401
    assert client.post("/kiosk/challenges", headers=H("trm_faux")).status_code == 401
    assert client.get("/kiosk/me", headers={"Authorization": f"Bearer {terminal['key']}"}).status_code == 401  # pas un jeton utilisateur

    info = client.get("/kiosk/me", headers=H(terminal["key"])).json()
    assert info["name"] == "Borne 1" and info["organisation_name"] and info["fingerprint_required"] is True
    assert db.scalars(select(Terminal)).one().last_seen_at is not None

    client.patch(f"/terminals/{terminal['id']}", json={"is_active": False}, headers=admin)
    assert client.get("/kiosk/me", headers=H(terminal["key"])).status_code == 401


# ------------------------------------------------------------------ défi de vivacité

def test_challenges_are_random_distinct_and_single_use(ctx):
    client, db, _, admin, terminal = ctx
    seen = set()
    for _ in range(25):
        ch = challenge(client, terminal["key"])
        assert len(ch["steps"]) == 2 and len(set(ch["steps"])) == 2 and set(ch["steps"]) <= set(STEPS)
        seen.add(tuple(ch["steps"]))
    assert len(seen) >= 6  # pas prévisible

    ch = challenge(client, terminal["key"])
    frames = liveness_frames(ch["steps"])
    payload = {"challenge_id": ch["challenge_id"], "frames": frames}
    first = client.post("/kiosk/attempts", json=payload, headers=H(terminal["key"]))
    assert first.status_code == 200
    assert client.post("/kiosk/attempts", json=payload, headers=H(terminal["key"])).status_code == 400  # rejeu


def test_expired_unknown_and_foreign_challenges_are_refused(ctx):
    client, db, org, admin, terminal = ctx
    other = make_terminal(client, admin, name="Borne 2")
    ch = challenge(client, terminal["key"])
    frames = liveness_frames(ch["steps"])

    assert client.post("/kiosk/attempts", json={"challenge_id": str(uuid.uuid4()), "frames": frames}, headers=H(terminal["key"])).status_code == 400
    assert client.post("/kiosk/attempts", json={"challenge_id": ch["challenge_id"], "frames": frames}, headers=H(other["key"])).status_code == 400

    from app.models import KioskChallenge

    row = db.get(KioskChallenge, uuid.UUID(ch["challenge_id"]))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    expired = client.post("/kiosk/attempts", json={"challenge_id": ch["challenge_id"], "frames": frames}, headers=H(terminal["key"]))
    assert expired.status_code == 400 and "expiré" in expired.json()["detail"]


# ------------------------------------------------------------------ parcours réussi

def test_full_clock_in_with_face_and_fingerprint(ctx):
    client, db, _, admin, terminal = ctx
    pid, auth = enrolled_person(client, admin)
    key = terminal["key"]

    first = attempt(client, key, good()).json()
    assert first["status"] == "pending_fingerprint" and first["person"]["display_name"] == "Awa D."
    assert "record" not in first or first["record"] is None  # rien n'est enregistré avant l'empreinte
    assert db.scalars(select(AttendanceRecord)).all() == []
    allowed = first["webauthn"]["options"]["allowCredentials"]
    assert len(allowed) == 1  # uniquement les clés de la personne reconnue

    credential = auth.authenticate(first["webauthn"]["options"])
    done = client.post(f"/kiosk/attempts/{first['attempt_id']}/fingerprint", json={"credential": credential}, headers=H(key)).json()
    assert done["status"] == "success" and done["record"]["kind"] == "in" and done["record"]["method"] == "face+fingerprint"

    record = db.scalars(select(AttendanceRecord)).one()
    assert str(record.person_id) == pid and record.terminal_id == uuid.UUID(terminal["id"]) and record.face_score > 0.9
    log = db.scalars(select(AttendanceAttempt).where(AttendanceAttempt.status == "success")).one()
    assert log.face_score == record.face_score and log.details["steps"]

    listed = client.get("/attendance", headers=admin).json()
    assert listed["total"] == 1 and listed["items"][0]["person_name"] == "Awa Diop" and listed["items"][0]["terminal_name"] == "Borne 1"


def test_entries_and_exits_alternate(ctx, monkeypatch):
    client, _, _, admin, terminal = ctx
    monkeypatch.setattr(settings, "attendance_min_interval_seconds", 0)
    _, auth = enrolled_person(client, admin)
    kinds = [clock_in(client, terminal["key"], auth).json()["record"]["kind"] for _ in range(3)]
    assert kinds == ["in", "out", "in"]


def test_a_new_day_always_starts_with_an_entry(ctx, monkeypatch):
    client, db, org, admin, terminal = ctx
    monkeypatch.setattr(settings, "attendance_min_interval_seconds", 0)
    pid, auth = enrolled_person(client, admin)
    db.add(AttendanceRecord(organisation_id=org.id, person_id=uuid.UUID(pid), kind="in", occurred_at=utcnow() - timedelta(days=1), method="face"))
    db.commit()  # hier : entrée sans sortie (oubli de pointer)
    assert clock_in(client, terminal["key"], auth).json()["record"]["kind"] == "in"


def test_double_scan_is_refused(ctx):
    client, _, _, admin, terminal = ctx
    _, auth = enrolled_person(client, admin)
    assert clock_in(client, terminal["key"], auth).json()["status"] == "success"
    again = clock_in(client, terminal["key"], auth).json()
    assert again["status"] == "rejected" and again["reason"] == "too_soon" and "Déjà pointé" in again["message"]


# ------------------------------------------------------------------ vivacité : fraudes et erreurs

@pytest.mark.parametrize(
    "name, frames_for, reason",
    [
        ("photo immobile", lambda steps: [make_image(1, 0, 0)] * 14, "movement_missing"),
        ("mauvaise direction", lambda steps: liveness_frames(steps, do=[{"left": "right", "right": "left", "up": "down", "down": "up"}[s] for s in steps]), "movement_missing"),
        ("mouvements dans le désordre", lambda steps: liveness_frames(steps, do=list(reversed(steps))), "movement_missing"),
        ("une seule personne puis une autre", lambda steps: liveness_frames(steps, 1, identity_after_first_step=2), "identity_changed"),
        ("départ de travers", lambda steps: [make_image(1, 30, 0)] * 4 + liveness_frames(steps, baseline=0), "not_frontal_start"),
        ("image floue au départ", lambda steps: liveness_frames(steps, kind="blurry"), "poor_quality"),
        ("aucun visage", lambda steps: [make_image(1, kind="noface")] * 14, "no_continuous_face"),
        ("deux visages", lambda steps: [make_image(1, kind="two")] * 14, "several_faces"),
        ("visage trop petit", lambda steps: [make_image(1, kind="small")] * 4 + liveness_frames(steps, baseline=0), "poor_quality"),
    ],
)
def test_liveness_failures_are_refused_and_logged(ctx, name, frames_for, reason):
    client, db, _, admin, terminal = ctx
    enrolled_person(client, admin)
    body = attempt(client, terminal["key"], frames_for).json()
    assert body["status"] == "failed", name
    assert body["reason"] == reason and body["message"] and body["webauthn"] is None and body["person"] is None
    assert db.scalars(select(AttendanceRecord)).all() == []
    assert db.scalars(select(AttendanceAttempt).where(AttendanceAttempt.status == "failed_liveness")).all()


def test_unreadable_images_count_as_missing_faces(ctx):
    client, _, _, admin, terminal = ctx
    enrolled_person(client, admin)
    junk = "A" * 400
    body = attempt(client, terminal["key"], lambda steps: [junk] * 14).json()
    assert body["status"] == "failed" and body["reason"] == "no_continuous_face"


def test_payload_limits(ctx):
    client, _, _, admin, terminal = ctx
    ch = challenge(client, terminal["key"])
    too_few = client.post("/kiosk/attempts", json={"challenge_id": ch["challenge_id"], "frames": [make_image(1)] * 3}, headers=H(terminal["key"]))
    assert too_few.status_code == 422


# ------------------------------------------------------------------ reconnaissance

def test_unknown_face_is_refused(ctx):
    client, db, _, admin, terminal = ctx
    enrolled_person(client, admin, identity=1)
    body = attempt(client, terminal["key"], good(identity=99)).json()
    assert body["status"] == "failed" and body["reason"] == "unknown" and body["message"] == "Visage non reconnu"
    assert body["person"] is None and body["webauthn"] is None
    log = db.scalars(select(AttendanceAttempt).where(AttendanceAttempt.status == "failed_face")).one()
    assert log.person_id is None and log.face_score is not None


def test_empty_gallery_means_unknown(ctx):
    client, _, _, _, terminal = ctx
    assert attempt(client, terminal["key"], good()).json()["reason"] == "unknown"


def test_each_person_is_recognised_as_themselves(ctx, monkeypatch):
    client, _, _, admin, terminal = ctx
    monkeypatch.setattr(settings, "attendance_min_interval_seconds", 0)
    _, auth_a = enrolled_person(client, admin, identity=1, matricule="E1", first="Awa", last="Diop")
    _, auth_b = enrolled_person(client, admin, identity=2, matricule="E2", first="Moussa", last="Fall")
    first = attempt(client, terminal["key"], good(identity=2)).json()
    assert first["person"]["display_name"] == "Moussa F."
    # son empreinte à elle ne passe pas pour lui
    credential = auth_a.authenticate(first["webauthn"]["options"])
    wrong = client.post(f"/kiosk/attempts/{first['attempt_id']}/fingerprint", json={"credential": credential}, headers=H(terminal["key"])).json()
    assert wrong["status"] == "failed" and wrong["reason"] == "fingerprint_failed"


def test_gallery_decision_rules():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ranked = gallery.best_matches([a, a, b, c], np.array([0.30, 0.80, 0.20, 0.10]))
    assert ranked[0] == (a, pytest.approx(0.80)) and len(ranked) == 3  # 5 gabarits d'une personne = 1 candidat

    assert gallery.decide(ranked).person_id == a
    assert gallery.decide([(a, 0.30), (b, 0.1)]).reason == "unknown"  # sous le seuil
    ambiguous = gallery.decide([(a, 0.60), (b, 0.58)])
    assert ambiguous.person_id is None and ambiguous.reason == "ambiguous"  # deux personnes trop proches
    assert gallery.decide([]).reason == "unknown"
    assert gallery.decide([(a, 0.60)]).person_id == a  # seul candidat


def test_gallery_follows_enrolment_changes(ctx, monkeypatch):
    client, _, _, admin, terminal = ctx
    monkeypatch.setattr(settings, "attendance_min_interval_seconds", 0)
    pid, auth = enrolled_person(client, admin, identity=1)
    assert attempt(client, terminal["key"], good(identity=1)).json()["status"] == "pending_fingerprint"  # charge le cache

    # retrait du consentement : les gabarits disparaissent, le terminal ne reconnaît plus la personne
    assert client.delete(f"/persons/{pid}/consent", headers=admin).status_code == 204
    assert attempt(client, terminal["key"], good(identity=1)).json()["reason"] == "unknown"

    # nouveau consentement et nouvel enrôlement avec un autre visage : c'est lui qui est reconnu
    from tests.fakes import capture_set
    from tests.flows import CONSENT

    client.post(f"/persons/{pid}/consent", json=CONSENT, headers=admin)
    client.post(f"/persons/{pid}/face/enroll", json={"images": capture_set(identity=7)}, headers=admin)
    assert attempt(client, terminal["key"], good(identity=1)).json()["reason"] == "unknown"
    # le nouveau visage est reconnu (le retrait du consentement avait aussi supprimé l'empreinte)
    recognised = attempt(client, terminal["key"], good(identity=7)).json()
    assert recognised["status"] == "rejected" and recognised["reason"] == "no_fingerprint"


def test_a_terminal_only_sees_its_own_organisation(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    admin_a = org_admin(client, db_session, org_a, "a@x.sn")
    admin_b = org_admin(client, db_session, org_b, "b@x.sn")
    enrolled_person(client, admin_a, identity=1)
    terminal_b = make_terminal(client, admin_b)
    assert attempt(client, terminal_b["key"], good(identity=1)).json()["reason"] == "unknown"


# ------------------------------------------------------------------ empreinte et règles de la personne

def test_fingerprint_attempt_cannot_be_reused_or_forged(ctx, monkeypatch):
    client, db, _, admin, terminal = ctx
    monkeypatch.setattr(settings, "attendance_min_interval_seconds", 0)
    key = terminal["key"]
    _, auth = enrolled_person(client, admin)

    first = attempt(client, key, good()).json()
    url = f"/kiosk/attempts/{first['attempt_id']}/fingerprint"
    forged = client.post(url, json={"credential": auth.authenticate(first["webauthn"]["options"], tamper=True)}, headers=H(key)).json()
    assert forged["status"] == "failed" and db.scalars(select(AttendanceRecord)).all() == []
    # une tentative échouée est terminée : on ne peut pas réessayer avec la même
    assert client.post(url, json={"credential": auth.authenticate(first["webauthn"]["options"])}, headers=H(key)).status_code == 409

    second = attempt(client, key, good()).json()
    ok = client.post(f"/kiosk/attempts/{second['attempt_id']}/fingerprint", json={"credential": auth.authenticate(second["webauthn"]["options"])}, headers=H(key))
    assert ok.json()["status"] == "success"
    replay = client.post(f"/kiosk/attempts/{second['attempt_id']}/fingerprint", json={"credential": auth.authenticate(second["webauthn"]["options"])}, headers=H(key))
    assert replay.status_code == 409
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1


def test_attempt_belongs_to_its_terminal_and_expires(ctx):
    client, db, _, admin, terminal = ctx
    other = make_terminal(client, admin, name="Borne 2")
    _, auth = enrolled_person(client, admin)
    first = attempt(client, terminal["key"], good()).json()
    url = f"/kiosk/attempts/{first['attempt_id']}/fingerprint"
    credential = {"credential": auth.authenticate(first["webauthn"]["options"])}
    assert client.post(url, json=credential, headers=H(other["key"])).status_code == 404
    assert client.post(f"/kiosk/attempts/{uuid.uuid4()}/fingerprint", json=credential, headers=H(terminal["key"])).status_code == 404

    row = db.get(AttendanceAttempt, uuid.UUID(first["attempt_id"]))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    late = client.post(url, json=credential, headers=H(terminal["key"]))
    assert late.status_code == 410 and db.scalars(select(AttendanceRecord)).all() == []


def test_missing_fingerprint_is_refused_when_required_and_ignored_otherwise(ctx):
    client, db, _, admin, terminal = ctx
    enrolled_person(client, admin, fingerprint=False)
    body = attempt(client, terminal["key"], good()).json()
    assert body["status"] == "rejected" and body["reason"] == "no_fingerprint" and db.scalars(select(AttendanceRecord)).all() == []

    client.patch(f"/terminals/{terminal['id']}", json={"fingerprint_required": False}, headers=admin)
    ok = attempt(client, terminal["key"], good()).json()
    assert ok["status"] == "success" and ok["record"]["method"] == "face" and ok["webauthn"] is None


def test_suspended_person_cannot_clock_in(ctx):
    client, _, _, admin, terminal = ctx
    pid, _ = enrolled_person(client, admin)
    assert client.patch(f"/persons/{pid}", json={"status": "suspended"}, headers=admin).status_code == 200
    body = attempt(client, terminal["key"], good()).json()
    assert body["status"] == "rejected" and body["reason"] == "person_suspended" and body["webauthn"] is None


def test_engine_not_ready_returns_503(ctx, face_engine):
    client, _, _, admin, terminal = ctx
    enrolled_person(client, admin)
    face_engine.ready = False
    r = attempt(client, terminal["key"], good())
    assert r.status_code == 503 and "charge" in r.json()["detail"]


# ------------------------------------------------------------------ blocage anti-abus

def test_terminal_locks_after_repeated_failures(ctx, monkeypatch):
    client, _, _, admin, terminal = ctx
    key = terminal["key"]
    enrolled_person(client, admin)
    for _ in range(settings.kiosk_max_failures):
        assert attempt(client, key, good(identity=99)).json()["status"] == "failed"
    locked = client.post("/kiosk/challenges", headers=H(key))
    assert locked.status_code == 429 and locked.json()["retry_after"] > 0 and "Retry-After" in locked.headers
    # même un pointage légitime est suspendu pendant le blocage
    ch_frames = liveness_frames(["left", "up"])
    assert client.post("/kiosk/attempts", json={"challenge_id": str(uuid.uuid4()), "frames": ch_frames}, headers=H(key)).status_code == 429

    monkeypatch.setattr(settings, "kiosk_lockout_seconds", 0)  # le délai de blocage est écoulé
    assert client.post("/kiosk/challenges", headers=H(key)).status_code == 200


def test_failures_of_one_terminal_do_not_lock_another(ctx):
    client, _, _, admin, terminal = ctx
    other = make_terminal(client, admin, name="Borne 2")
    enrolled_person(client, admin)
    for _ in range(settings.kiosk_max_failures):
        attempt(client, terminal["key"], good(identity=99))
    assert client.post("/kiosk/challenges", headers=H(terminal["key"])).status_code == 429
    assert client.post("/kiosk/challenges", headers=H(other["key"])).status_code == 200


# ------------------------------------------------------------------ consultation des pointages

def test_attendance_listing_filters_and_permissions(ctx, db_session, monkeypatch):
    client, db, org, admin, terminal = ctx
    monkeypatch.setattr(settings, "attendance_min_interval_seconds", 0)
    pid_a, auth_a = enrolled_person(client, admin, identity=1, matricule="E1", first="Awa", last="Diop")
    pid_b, auth_b = enrolled_person(client, admin, identity=2, matricule="E2", first="Moussa", last="Fall")
    clock_in(client, terminal["key"], auth_a, identity=1)
    clock_in(client, terminal["key"], auth_a, identity=1)
    clock_in(client, terminal["key"], auth_b, identity=2)

    assert client.get("/attendance", headers=admin).json()["total"] == 3
    assert client.get(f"/attendance?person_id={pid_a}", headers=admin).json()["total"] == 2
    assert client.get("/attendance?kind=out", headers=admin).json()["total"] == 1
    assert client.get("/attendance?date=2000-01-01", headers=admin).json()["total"] == 0
    page = client.get("/attendance?limit=2", headers=admin).json()
    assert len(page["items"]) == 2 and page["total"] == 3

    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    make_user(db_session, "emp@ecole.sn", Role.PERSONNE, org)
    manager, employee = auth_headers(client, "chef@ecole.sn"), auth_headers(client, "emp@ecole.sn")
    assert client.get("/attendance", headers=manager).status_code == 200
    assert client.get("/attendance", headers=employee).status_code == 403
    assert client.get("/attendance").status_code == 401


def test_attempts_listing_shows_scores_to_admins_only(ctx, db_session):
    client, _, org, admin, terminal = ctx
    enrolled_person(client, admin)
    attempt(client, terminal["key"], good(identity=99))
    attempt(client, terminal["key"], good())
    rows = client.get("/attendance/attempts", headers=admin).json()
    assert {r["status"] for r in rows} == {"failed_face", "pending_fingerprint"}
    assert all(r["face_score"] is not None for r in rows) and rows[0]["terminal_name"] == "Borne 1"
    assert [r["status"] for r in client.get("/attendance/attempts?status=failed_face", headers=admin).json()] == ["failed_face"]

    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    assert client.get("/attendance/attempts", headers=auth_headers(client, "chef@ecole.sn")).status_code == 403


def test_attendance_is_isolated_between_organisations(client, db_session, monkeypatch):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    admin_a = org_admin(client, db_session, org_a, "a@x.sn")
    admin_b = org_admin(client, db_session, org_b, "b@x.sn")
    terminal = make_terminal(client, admin_a)
    _, auth = enrolled_person(client, admin_a)
    clock_in(client, terminal["key"], auth)
    assert client.get("/attendance", headers=admin_a).json()["total"] == 1
    assert client.get("/attendance", headers=admin_b).json()["total"] == 0
    assert client.get("/attendance/attempts", headers=admin_b).json() == []


def test_deleting_a_person_removes_their_attendance(ctx):
    client, db, _, admin, terminal = ctx
    pid, auth = enrolled_person(client, admin)
    clock_in(client, terminal["key"], auth)
    assert client.delete(f"/persons/{pid}", headers=admin).status_code == 204
    assert db.scalars(select(AttendanceRecord)).all() == []


def test_direction_flip_settings(monkeypatch):
    from app.biometrics.face.liveness import _reached
    from app.biometrics.face.types import Pose

    base = Pose(0, 0, 0)
    assert _reached("left", Pose(-24, 0, 0), base) and not _reached("left", Pose(24, 0, 0), base)
    assert _reached("up", Pose(0, -16, 0), base) and not _reached("up", Pose(0, 16, 0), base)
    assert not _reached("right", Pose(-24, 0, 0), base) and not _reached("down", Pose(0, -16, 0), base)

    monkeypatch.setattr(settings, "face_liveness_flip_yaw", True)
    assert _reached("left", Pose(24, 0, 0), base) and _reached("right", Pose(-24, 0, 0), base)
    assert _reached("up", Pose(0, -16, 0), base)  # l'axe vertical n'est pas touché

    monkeypatch.setattr(settings, "face_liveness_flip_pitch", True)
    assert _reached("up", Pose(0, 16, 0), base) and _reached("down", Pose(0, -16, 0), base)
