from app.core.roles import Role
from app.core.security import hash_password
from app.models import Organisation, User

PASSWORD = "MotDePasse-Solide-1"


def make_org(db, name="École A") -> Organisation:
    org = Organisation(name=name)
    db.add(org)
    db.commit()
    return org


def make_user(db, email, role=Role.PERSONNE, org=None, password=PASSWORD, **extra) -> User:
    user = User(
        email=email,
        full_name="Utilisateur Test",
        password_hash=hash_password(password),
        role=str(role),
        organisation_id=org.id if org else None,
        **extra,
    )
    db.add(user)
    db.commit()
    return user


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth_headers(client, email, password=PASSWORD, **extra_headers):
    tokens = login(client, email, password).json()
    return {"Authorization": f"Bearer {tokens['access_token']}", **extra_headers}


def org_admin(client, db, org, email="admin@ecole.sn"):
    """Crée un admin d'organisation et renvoie ses en-têtes d'authentification."""
    make_user(db, email, Role.ADMIN_ORGANISATION, org)
    return auth_headers(client, email)
