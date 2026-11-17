from sqlalchemy import select

from app.core.roles import Role
from app.models import AuditLog, Department
from tests.helpers import auth_headers, make_org, make_user, org_admin


def test_admin_site_crud_and_audit(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)

    created = client.post("/sites", json={"name": "Siège Dakar", "address": "Plateau"}, headers=headers)
    assert created.status_code == 201
    site = created.json()
    assert site["organisation_id"] == str(org.id)
    assert site["timezone"] == "Africa/Dakar"

    assert [s["name"] for s in client.get("/sites", headers=headers).json()] == ["Siège Dakar"]
    assert client.get(f"/sites/{site['id']}", headers=headers).status_code == 200

    patched = client.patch(f"/sites/{site['id']}", json={"address": "Almadies"}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["address"] == "Almadies"

    assert client.delete(f"/sites/{site['id']}", headers=headers).status_code == 204
    assert client.get(f"/sites/{site['id']}", headers=headers).status_code == 404

    actions = set(db_session.scalars(select(AuditLog.action)))
    assert {"site.created", "site.updated", "site.deleted"} <= actions


def test_name_unique_per_organisation_but_reusable_across_organisations(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")

    assert client.post("/sites", json={"name": "Siège"}, headers=headers_a).status_code == 201
    assert client.post("/sites", json={"name": "Siège"}, headers=headers_a).status_code == 409
    assert client.post("/sites", json={"name": "Siège"}, headers=headers_b).status_code == 201


def test_tenant_isolation_on_sites(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    site = client.post("/sites", json={"name": "Siège A"}, headers=headers_a).json()

    assert client.get("/sites", headers=headers_b).json() == []
    assert client.get(f"/sites/{site['id']}", headers=headers_b).status_code == 404
    assert client.patch(f"/sites/{site['id']}", json={"name": "Piraté"}, headers=headers_b).status_code == 404
    assert client.delete(f"/sites/{site['id']}", headers=headers_b).status_code == 404
    assert client.get(f"/sites/{site['id']}", headers=headers_a).json()["name"] == "Siège A"


def test_roles_manager_reads_but_cannot_write_personne_cannot_read(client, db_session):
    org = make_org(db_session)
    admin = org_admin(client, db_session, org)
    client.post("/sites", json={"name": "Siège"}, headers=admin)

    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    make_user(db_session, "emp@ecole.sn", Role.PERSONNE, org)
    manager = auth_headers(client, "chef@ecole.sn")
    employee = auth_headers(client, "emp@ecole.sn")

    assert client.get("/sites", headers=manager).status_code == 200
    assert client.post("/sites", json={"name": "Autre"}, headers=manager).status_code == 403
    assert client.get("/sites", headers=employee).status_code == 403
    assert client.get("/sites").status_code == 401


def test_super_admin_must_name_the_organisation_to_write(client, db_session):
    org = make_org(db_session)
    make_user(db_session, "root@pointage.sn", Role.SUPER_ADMIN)
    root = auth_headers(client, "root@pointage.sn")

    assert client.post("/sites", json={"name": "Siège"}, headers=root).status_code == 422
    with_header = {**root, "X-Organisation-Id": str(org.id)}
    assert client.post("/sites", json={"name": "Siège"}, headers=with_header).status_code == 201


def test_department_and_group_references_must_stay_in_the_organisation(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    site_b = client.post("/sites", json={"name": "Site B"}, headers=headers_b).json()

    bad_dept = client.post("/departments", json={"name": "Compta", "site_id": site_b["id"]}, headers=headers_a)
    assert bad_dept.status_code == 422

    site_a = client.post("/sites", json={"name": "Site A"}, headers=headers_a).json()
    dept = client.post("/departments", json={"name": "Compta", "site_id": site_a["id"]}, headers=headers_a)
    assert dept.status_code == 201

    bad_group = client.post(
        "/groups", json={"name": "6eA", "kind": "classe", "department_id": dept.json()["id"], "site_id": site_b["id"]},
        headers=headers_a,
    )
    assert bad_group.status_code == 422
    ok_group = client.post(
        "/groups", json={"name": "6eA", "kind": "classe", "department_id": dept.json()["id"]}, headers=headers_a
    )
    assert ok_group.status_code == 201
    assert ok_group.json()["kind"] == "classe"


def test_deleting_a_site_detaches_its_departments(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    site = client.post("/sites", json={"name": "Site"}, headers=headers).json()
    dept = client.post("/departments", json={"name": "RH", "site_id": site["id"]}, headers=headers).json()

    assert client.delete(f"/sites/{site['id']}", headers=headers).status_code == 204
    db_session.expire_all()
    assert db_session.scalar(select(Department.site_id).where(Department.name == "RH")) is None
    assert client.get(f"/departments/{dept['id']}", headers=headers).status_code == 200


def test_validation_errors(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    assert client.post("/sites", json={"name": "S", "timezone": "Mars/Olympus"}, headers=headers).status_code == 422
    assert client.post("/sites", json={"name": "A"}, headers=headers).status_code == 422
    assert client.post("/groups", json={"name": "X", "kind": "bizarre"}, headers=headers).status_code == 422
    site = client.post("/sites", json={"name": "Site"}, headers=headers).json()
    assert client.patch(f"/sites/{site['id']}", json={"name": None}, headers=headers).status_code == 422
