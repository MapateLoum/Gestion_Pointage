from sqlalchemy import select

from app.core.roles import Role
from app.models import AuditLog
from tests.helpers import auth_headers, make_org, make_user, org_admin


def person(matricule="EMP001", **extra):
    return {"matricule": matricule, "first_name": "Awa", "last_name": "Diop", **extra}


def test_create_person_with_site_department_and_groups(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    site = client.post("/sites", json={"name": "Siège"}, headers=headers).json()
    dept = client.post("/departments", json={"name": "RH"}, headers=headers).json()
    g1 = client.post("/groups", json={"name": "Équipe A"}, headers=headers).json()
    g2 = client.post("/groups", json={"name": "Équipe B"}, headers=headers).json()

    response = client.post(
        "/persons",
        json=person(
            email="Awa.Diop@Exemple.SN", phone="77 123 45 67", category="enseignant",
            site_id=site["id"], department_id=dept["id"], group_ids=[g1["id"], g2["id"]],
        ),
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["organisation_id"] == str(org.id)
    assert body["email"] == "awa.diop@exemple.sn"
    assert body["status"] == "active"
    assert set(body["group_ids"]) == {g1["id"], g2["id"]}
    assert "person.created" in set(db_session.scalars(select(AuditLog.action)))


def test_matricule_unique_per_organisation_only(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")

    assert client.post("/persons", json=person(), headers=headers_a).status_code == 201
    assert client.post("/persons", json=person(), headers=headers_a).status_code == 409
    assert client.post("/persons", json=person(), headers=headers_b).status_code == 201


def test_cannot_reference_site_or_group_of_another_organisation(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    site_b = client.post("/sites", json={"name": "Site B"}, headers=headers_b).json()
    group_b = client.post("/groups", json={"name": "Groupe B"}, headers=headers_b).json()

    assert client.post("/persons", json=person(site_id=site_b["id"]), headers=headers_a).status_code == 422
    assert client.post("/persons", json=person(group_ids=[group_b["id"]]), headers=headers_a).status_code == 422
    assert client.get("/persons", headers=headers_a).json()["total"] == 0


def test_list_search_filters_and_pagination(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    group = client.post("/groups", json={"name": "6eA", "kind": "classe"}, headers=headers).json()

    names = [("E1", "Awa", "Diop"), ("E2", "Moussa", "Fall"), ("E3", "Fatou", "Diop"),
             ("E4", "Ibrahima", "Sow"), ("E5", "Aminata", "Ndiaye")]
    for matricule, first, last in names:
        extra = {"group_ids": [group["id"]]} if matricule in ("E1", "E2") else {}
        r = client.post("/persons", json={"matricule": matricule, "first_name": first, "last_name": last, **extra}, headers=headers)
        assert r.status_code == 201

    page = client.get("/persons?limit=2&offset=0", headers=headers).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    assert [p["last_name"] for p in page["items"]] == ["Diop", "Diop"]  # tri par nom puis prénom

    assert client.get("/persons?q=diop", headers=headers).json()["total"] == 2
    assert client.get("/persons?q=e4", headers=headers).json()["total"] == 1  # par matricule
    assert client.get(f"/persons?group_id={group['id']}", headers=headers).json()["total"] == 2
    assert client.get("/persons?category=eleve", headers=headers).json()["total"] == 0
    assert client.get("/persons?limit=0", headers=headers).status_code == 422


def test_update_person_groups_site_and_conflicts(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    site = client.post("/sites", json={"name": "Siège"}, headers=headers).json()
    g1 = client.post("/groups", json={"name": "G1"}, headers=headers).json()
    g2 = client.post("/groups", json={"name": "G2"}, headers=headers).json()
    created = client.post("/persons", json=person(site_id=site["id"], group_ids=[g1["id"]]), headers=headers).json()
    client.post("/persons", json=person("EMP002"), headers=headers)

    patched = client.patch(
        f"/persons/{created['id']}",
        json={"site_id": None, "group_ids": [g2["id"]], "status": "suspended"},
        headers=headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["site_id"] is None
    assert body["group_ids"] == [g2["id"]]
    assert body["status"] == "suspended"

    assert client.patch(f"/persons/{created['id']}", json={"matricule": "EMP002"}, headers=headers).status_code == 409
    assert client.patch(f"/persons/{created['id']}", json={"first_name": None}, headers=headers).status_code == 422


def test_delete_person_and_isolation(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    created = client.post("/persons", json=person(), headers=headers_a).json()

    assert client.get(f"/persons/{created['id']}", headers=headers_b).status_code == 404
    assert client.patch(f"/persons/{created['id']}", json={"last_name": "X"}, headers=headers_b).status_code == 404
    assert client.delete(f"/persons/{created['id']}", headers=headers_b).status_code == 404

    assert client.delete(f"/persons/{created['id']}", headers=headers_a).status_code == 204
    assert client.get(f"/persons/{created['id']}", headers=headers_a).status_code == 404


def test_person_permissions(client, db_session):
    org = make_org(db_session)
    admin = org_admin(client, db_session, org)
    client.post("/persons", json=person(), headers=admin)
    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    make_user(db_session, "emp@ecole.sn", Role.PERSONNE, org)
    manager = auth_headers(client, "chef@ecole.sn")
    employee = auth_headers(client, "emp@ecole.sn")

    assert client.get("/persons", headers=manager).json()["total"] == 1
    assert client.post("/persons", json=person("EMP9"), headers=manager).status_code == 403
    assert client.get("/persons", headers=employee).status_code == 403


def test_person_validation(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    assert client.post("/persons", json=person(phone="abc"), headers=headers).status_code == 422
    assert client.post("/persons", json=person(email="pas-un-email"), headers=headers).status_code == 422
    assert client.post("/persons", json=person(matricule="a b"), headers=headers).status_code == 422
    assert client.post("/persons", json=person(category="alien"), headers=headers).status_code == 422
