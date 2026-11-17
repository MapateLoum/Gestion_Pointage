from sqlalchemy import select

from app.core.roles import Role
from app.models import AuditLog, Person
from tests.helpers import auth_headers, make_org, make_user, org_admin


def upload(client, headers, content, params="", filename="personnes.csv"):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return client.post(
        f"/persons/import-csv{params}", headers=headers,
        files={"file": (filename, data, "text/csv")},
    )


def setup_structure(client, headers):
    client.post("/sites", json={"name": "Siège Dakar"}, headers=headers)
    client.post("/departments", json={"name": "Administration"}, headers=headers)
    client.post("/groups", json={"name": "6eA", "kind": "classe"}, headers=headers)
    client.post("/groups", json={"name": "Maths"}, headers=headers)


GOOD_CSV = (
    "\ufeffMatricule;Nom;Prénom;Email;Téléphone;Catégorie;Site;Département;Groupes\n"
    "EMP001;Diop;Awa;awa@exemple.sn;77 123 45 67;Enseignant;Siège Dakar;Administration;6eA|Maths\n"
    "EMP002;Fall;Moussa;;;eleve;;;6ea\n"
    "\n"
    "EMP003;Sow;Fatou;;;;;;\n"
)


def test_template_download(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    response = client.get("/persons/import-template", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "matricule;nom;prenom" in response.text


def test_successful_import_handles_bom_accents_and_blank_lines(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    setup_structure(client, headers)

    response = upload(client, headers, GOOD_CSV)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 3 and body["total_rows"] == 3 and body["errors"] == []

    persons = {p["matricule"]: p for p in client.get("/persons", headers=headers).json()["items"]}
    assert persons["EMP001"]["category"] == "enseignant"
    assert persons["EMP001"]["email"] == "awa@exemple.sn"
    assert len(persons["EMP001"]["group_ids"]) == 2
    assert len(persons["EMP002"]["group_ids"]) == 1  # « 6ea » retrouve « 6eA »
    assert persons["EMP003"]["category"] == "employe"  # valeur par défaut
    assert "person.imported" in set(db_session.scalars(select(AuditLog.action)))


def test_comma_delimiter_is_supported(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    csv_text = "matricule,nom,prenom\nA1,Diop,Awa\nA2,Fall,Moussa\n"
    assert upload(client, headers, csv_text).json()["imported"] == 2


def test_dry_run_validates_without_importing(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    setup_structure(client, headers)

    body = upload(client, headers, GOOD_CSV, "?dry_run=true").json()
    assert body["dry_run"] is True and body["valid_rows"] == 3 and body["imported"] == 0
    assert db_session.scalars(select(Person)).all() == []


def test_any_error_blocks_the_whole_import_with_line_numbers(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    setup_structure(client, headers)
    client.post("/persons", json={"matricule": "EXIST", "first_name": "A", "last_name": "B"}, headers=headers)

    bad = (
        "matricule;nom;prenom;email;telephone;categorie;site;departement;groupes\n"
        "OK1;Diop;Awa;;;;;;\n"                       # ligne 2 : valide
        "OK1;Fall;Moussa;;;;;;\n"                    # ligne 3 : doublon dans le fichier
        "EXIST;Sow;Fatou;;;;;;\n"                    # ligne 4 : déjà en base
        "X3;;Ibra;;;;;;\n"                           # ligne 5 : nom manquant
        "X4;Ba;Ami;pas-un-mail;;;;;\n"               # ligne 6 : email invalide
        "X5;Ba;Ami;;;;Site Fantôme;;\n"              # ligne 7 : site inconnu
        "X6;Ba;Ami;;;;;;Groupe Fantôme\n"            # ligne 8 : groupe inconnu
        "X7;Ba;Ami;;;alien;;;\n"                     # ligne 9 : catégorie invalide
    )
    response = upload(client, headers, bad)
    assert response.status_code == 422
    body = response.json()
    assert body["imported"] == 0
    lines = {e["line"] for e in body["errors"]}
    assert lines == {3, 4, 5, 6, 7, 8, 9}
    # Rien n'a été importé : seule la personne créée à la main existe.
    assert [p.matricule for p in db_session.scalars(select(Person))] == ["EXIST"]


def test_missing_required_column(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    response = upload(client, headers, "matricule;nom\nA1;Diop\n")
    assert response.status_code == 422
    assert "prenom" in response.json()["errors"][0]["message"]


def test_create_groups_option(client, db_session):
    org = make_org(db_session)
    headers = org_admin(client, db_session, org)
    csv_text = "matricule;nom;prenom;groupes\nA1;Diop;Awa;5eB|5eC\nA2;Fall;Moussa;5eB\n"

    assert upload(client, headers, csv_text).status_code == 422  # groupes inconnus
    response = upload(client, headers, csv_text, "?create_groups=true")
    assert response.status_code == 200
    assert response.json()["groups_created"] == 2
    assert {g["name"] for g in client.get("/groups", headers=headers).json()} == {"5eB", "5eC"}


def test_import_is_isolated_per_organisation(client, db_session):
    org_a, org_b = make_org(db_session, "A"), make_org(db_session, "B")
    headers_a = org_admin(client, db_session, org_a, "a@x.sn")
    headers_b = org_admin(client, db_session, org_b, "b@x.sn")
    csv_text = "matricule;nom;prenom\nA1;Diop;Awa\n"

    assert upload(client, headers_a, csv_text).json()["imported"] == 1
    assert client.get("/persons", headers=headers_b).json()["total"] == 0
    assert upload(client, headers_b, csv_text).json()["imported"] == 1  # même matricule, autre organisation


def test_import_permissions_and_limits(client, db_session):
    org = make_org(db_session)
    admin = org_admin(client, db_session, org)
    make_user(db_session, "chef@ecole.sn", Role.MANAGER, org)
    manager = auth_headers(client, "chef@ecole.sn")
    csv_text = "matricule;nom;prenom\nA1;Diop;Awa\n"

    assert upload(client, manager, csv_text).status_code == 403
    assert client.get("/persons/import-template", headers=manager).status_code == 403
    assert upload(client, admin, b"x" * (2 * 1024 * 1024 + 10)).status_code == 413
    assert upload(client, admin, "").status_code == 422
