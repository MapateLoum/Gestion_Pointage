import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.roles import Role
from app.models import AuditLog, User
from app.repositories.base import TenantRepository
from tests.helpers import PASSWORD, auth_headers, make_org, make_user

NEW_USER = {
    "email": "prof@ecole.sn",
    "full_name": "Awa Diop",
    "password": "AutreMotDePasse-2",
    "role": "personne",
}


def test_personne_cannot_create_users(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "employe@ecole.sn", Role.PERSONNE, org)
    headers = auth_headers(client, "employe@ecole.sn")

    assert client.post("/users", json=NEW_USER, headers=headers).status_code == 403
    assert client.get("/users", headers=headers).status_code == 403


def test_org_admin_creates_users_in_own_org_only(client, db_session):
    org = make_org(db_session)
    other = make_org(db_session, "Entreprise B")
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)
    headers = auth_headers(client, "admin@ecole.sn")

    created = client.post("/users", json=NEW_USER, headers=headers)
    assert created.status_code == 201
    assert created.json()["organisation_id"] == str(org.id)
    assert "password" not in created.json() and "password_hash" not in created.json()

    # Ne peut pas créer dans une autre organisation...
    elsewhere = {**NEW_USER, "email": "x@ecole.sn", "organisation_id": str(other.id)}
    assert client.post("/users", json=elsewhere, headers=headers).status_code == 403
    # ...ni un admin ni un super_admin.
    for role in ("admin_organisation", "super_admin"):
        forbidden = {**NEW_USER, "email": f"{role}@ecole.sn", "role": role}
        assert client.post("/users", json=forbidden, headers=headers).status_code == 403


def test_duplicate_email_is_rejected(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)
    headers = auth_headers(client, "admin@ecole.sn")

    assert client.post("/users", json=NEW_USER, headers=headers).status_code == 201
    assert client.post("/users", json=NEW_USER, headers=headers).status_code == 409


def test_short_password_is_rejected(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)
    headers = auth_headers(client, "admin@ecole.sn")
    assert client.post("/users", json={**NEW_USER, "password": "court"}, headers=headers).status_code == 422


def test_admin_cannot_see_other_organisation_users(client, db_session):
    org_a = make_org(db_session, "École A")
    org_b = make_org(db_session, "Entreprise B")
    make_user(db_session, "admin-a@ecole.sn", Role.ADMIN_ORGANISATION, org_a)
    user_b = make_user(db_session, "employe-b@entreprise.sn", Role.PERSONNE, org_b)
    headers = auth_headers(client, "admin-a@ecole.sn")

    emails = [u["email"] for u in client.get("/users", headers=headers).json()]
    assert "admin-a@ecole.sn" in emails
    assert "employe-b@entreprise.sn" not in emails

    # Accès direct par identifiant : 404, comme si le compte n'existait pas.
    assert client.get(f"/users/{user_b.id}", headers=headers).status_code == 404


def test_admin_cannot_switch_organisation_with_header(client, db_session):
    org_a = make_org(db_session, "École A")
    org_b = make_org(db_session, "Entreprise B")
    make_user(db_session, "admin-a@ecole.sn", Role.ADMIN_ORGANISATION, org_a)
    headers = auth_headers(client, "admin-a@ecole.sn", **{"X-Organisation-Id": str(org_b.id)})
    assert client.get("/users", headers=headers).status_code == 403


def test_only_super_admin_manages_organisations(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "admin@ecole.sn", Role.ADMIN_ORGANISATION, org)
    make_user(db_session, "root@pointage.sn", Role.SUPER_ADMIN)

    admin_headers = auth_headers(client, "admin@ecole.sn")
    assert client.post("/organisations", json={"name": "Nouvelle org"}, headers=admin_headers).status_code == 403
    assert client.get("/organisations", headers=admin_headers).status_code == 403

    root_headers = auth_headers(client, "root@pointage.sn")
    created = client.post("/organisations", json={"name": "Clinique Teranga", "type": "entreprise"}, headers=root_headers)
    assert created.status_code == 201
    assert len(client.get("/organisations", headers=root_headers).json()) == 2


def test_super_admin_creates_org_admin_and_can_scope_by_header(client, db_session):
    org_a = make_org(db_session, "École A")
    org_b = make_org(db_session, "Entreprise B")
    make_user(db_session, "root@pointage.sn", Role.SUPER_ADMIN)
    make_user(db_session, "employe-a@ecole.sn", Role.PERSONNE, org_a)
    make_user(db_session, "employe-b@entreprise.sn", Role.PERSONNE, org_b)
    headers = auth_headers(client, "root@pointage.sn")

    payload = {**NEW_USER, "role": "admin_organisation", "organisation_id": str(org_a.id)}
    assert client.post("/users", json=payload, headers=headers).status_code == 201
    # organisation_id obligatoire pour un super_admin
    no_org = {**NEW_USER, "email": "z@ecole.sn", "role": "admin_organisation"}
    assert client.post("/users", json=no_org, headers=headers).status_code == 422

    everything = client.get("/users", headers=headers).json()
    assert len(everything) == 4

    scoped_headers = {**headers, "X-Organisation-Id": str(org_b.id)}
    scoped = client.get("/users", headers=scoped_headers).json()
    assert [u["email"] for u in scoped] == ["employe-b@entreprise.sn"]


def test_audit_logs_are_scoped_to_organisation(client, db_session):
    org_a = make_org(db_session, "École A")
    org_b = make_org(db_session, "Entreprise B")
    make_user(db_session, "admin-a@ecole.sn", Role.ADMIN_ORGANISATION, org_a)
    make_user(db_session, "admin-b@entreprise.sn", Role.ADMIN_ORGANISATION, org_b)
    headers_a = auth_headers(client, "admin-a@ecole.sn")
    auth_headers(client, "admin-b@entreprise.sn")

    client.post("/users", json=NEW_USER, headers=headers_a)

    logs = client.get("/audit-logs", headers=headers_a).json()
    assert logs, "l'admin A doit voir ses propres événements"
    assert {entry["organisation_id"] for entry in logs} == {str(org_a.id)}
    assert "user.created" in {entry["action"] for entry in logs}

    only_created = client.get("/audit-logs?action=user.created", headers=headers_a).json()
    assert [entry["action"] for entry in only_created] == ["user.created"]


def test_audit_endpoint_forbidden_for_manager(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    assert client.get("/audit-logs", headers=auth_headers(client, "chef@ecole.sn")).status_code == 403


def test_tenant_repository_isolation(db_session):
    org_a = make_org(db_session, "A")
    org_b = make_org(db_session, "B")
    user_a = make_user(db_session, "a@x.sn", Role.PERSONNE, org_a)
    user_b = make_user(db_session, "b@x.sn", Role.PERSONNE, org_b)

    repo_a = TenantRepository(db_session, User, org_a.id)
    assert [u.id for u in repo_a.list()] == [user_a.id]
    assert repo_a.get(user_b.id) is None
    assert repo_a.get(user_a.id) is not None

    global_repo = TenantRepository(db_session, User, None)
    assert len(global_repo.list()) == 2


def test_database_rejects_inconsistent_role_and_organisation(db_session):
    org = make_org(db_session)
    with pytest.raises(IntegrityError):
        make_user(db_session, "root@x.sn", Role.SUPER_ADMIN, org)
    db_session.rollback()
    with pytest.raises(IntegrityError):
        make_user(db_session, "emp@x.sn", Role.PERSONNE, None)
