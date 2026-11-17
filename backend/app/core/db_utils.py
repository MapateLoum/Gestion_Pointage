from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def commit_or_conflict(db: Session, message: str = "Cette valeur existe déjà") -> None:
    """Commit ; si une contrainte d'unicité saute (course entre deux requêtes),
    on renvoie un 409 propre au lieu d'une erreur 500."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, message)
