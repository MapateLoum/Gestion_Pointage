"""Crée le premier compte super_admin.

Usage (dans le conteneur) :
    python -m app.scripts.create_super_admin --email toi@exemple.com --full-name "Ton Nom"
Le mot de passe est demandé de façon masquée.
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.roles import Role
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import User
from app.services import audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Créer un super_admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Mot de passe (10 caractères minimum) : ")
    if len(password) < 10:
        sys.exit("Mot de passe trop court (10 caractères minimum).")
    if password != getpass.getpass("Confirme le mot de passe : "):
        sys.exit("Les mots de passe ne correspondent pas.")

    email = args.email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            sys.exit("Un compte avec cet email existe déjà.")
        user = User(
            organisation_id=None,
            email=email,
            full_name=args.full_name.strip(),
            password_hash=hash_password(password),
            role=str(Role.SUPER_ADMIN),
        )
        db.add(user)
        db.flush()
        audit.record(
            db,
            action="user.super_admin_created",
            object_type="user",
            object_id=str(user.id),
            details={"email": email, "via": "script"},
        )
        db.commit()
    print(f"Super admin créé : {email}")


if __name__ == "__main__":
    main()
