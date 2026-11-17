from sqlalchemy import select

from app.core.roles import Role
from app.models import AuditLog
from tests.helpers import PASSWORD, auth_headers, login, make_org, make_user


def test_login_success_and_me(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)

    response = login(client, "admin@ecole.sn")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]

    me = client.get("/auth/me", headers=auth_headers(client, "admin@ecole.sn"))
    assert me.status_code == 200
    assert me.json()["email"] == "admin@ecole.sn"
    assert me.json()["role"] == "admin_organisation"


def test_login_email_is_case_insensitive(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)
    assert login(client, "ADMIN@Ecole.SN").status_code == 200


def test_login_wrong_password_is_401_and_audited(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)

    response = login(client, "admin@ecole.sn", "mauvais-mot-de-passe")
    assert response.status_code == 401

    actions = db_session.scalars(select(AuditLog.action)).all()
    assert "auth.login_failed" in actions


def test_unknown_email_gives_same_error_as_wrong_password(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)

    unknown = login(client, "inconnu@ecole.sn", "peu-importe-1234")
    wrong = login(client, "admin@ecole.sn", "peu-importe-1234")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_account_locks_after_too_many_failures(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)

    for _ in range(5):
        assert login(client, "admin@ecole.sn", "mauvais-mot-de-passe").status_code == 401

    # Même avec le BON mot de passe, le compte est verrouillé.
    assert login(client, "admin@ecole.sn", PASSWORD).status_code == 429


def test_inactive_user_cannot_login(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org, is_active=False)
    assert login(client, "admin@ecole.sn").status_code == 401


def test_protected_route_requires_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    bad = client.get("/auth/me", headers={"Authorization": "Bearer pas-un-vrai-jeton"})
    assert bad.status_code == 401


def test_refresh_rotates_and_reuse_revokes_everything(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)

    first = login(client, "admin@ecole.sn").json()
    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    new_refresh = second.json()["refresh_token"]
    assert new_refresh != first["refresh_token"]

    # Réutiliser l'ancien jeton = alerte : il est refusé...
    reuse = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401
    # ...et le jeton légitime issu de la rotation est aussi révoqué.
    assert client.post("/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401

    actions = db_session.scalars(select(AuditLog.action)).all()
    assert "auth.refresh_reuse_detected" in actions


def test_logout_revokes_refresh_token(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)

    tokens = login(client, "admin@ecole.sn").json()
    assert client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
