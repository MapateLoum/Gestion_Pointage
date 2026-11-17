"""Galerie des visages d'une organisation : compare un visage inconnu à tous les gabarits enrôlés (1:N).

Les gabarits sont chiffrés en base. On les déchiffre une fois et on les garde EN MÉMOIRE, par organisation ;
le cache se renouvelle tout seul dès qu'un enrôlement ou une suppression change l'empreinte (nombre, date) des gabarits.
"""
import threading
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import crypto
from app.models import FaceTemplate


@dataclass
class _Entry:
    signature: tuple
    person_ids: list[uuid.UUID]
    matrix: np.ndarray  # (gabarits, dimension)


@dataclass
class Match:
    person_id: uuid.UUID | None
    score: float  # meilleure similarité trouvée (même si insuffisante)
    margin: float  # écart avec la 2e personne la plus proche
    reason: str | None = None  # "unknown" | "ambiguous" | None


_cache: dict[uuid.UUID, _Entry] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _load(db: Session, org_id: uuid.UUID, model_name: str) -> _Entry:
    signature = tuple(
        db.execute(
            select(func.count(FaceTemplate.id), func.max(FaceTemplate.created_at)).where(
                FaceTemplate.organisation_id == org_id, FaceTemplate.model_name == model_name
            )
        ).one()
    ) + (model_name,)
    with _lock:
        cached = _cache.get(org_id)
        if cached and cached.signature == signature:
            return cached
        rows = db.execute(
            select(FaceTemplate.person_id, FaceTemplate.pose, FaceTemplate.embedding).where(
                FaceTemplate.organisation_id == org_id, FaceTemplate.model_name == model_name
            )
        ).all()
        ids = [r.person_id for r in rows]
        vectors = [crypto.decrypt_embedding(r.embedding, crypto.template_aad(org_id, r.person_id, r.pose)) for r in rows]
        matrix = np.stack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32)
        entry = _Entry(signature, ids, matrix)
        _cache[org_id] = entry
        return entry


def best_matches(person_ids: list[uuid.UUID], similarities: np.ndarray) -> list[tuple[uuid.UUID, float]]:
    """Meilleure similarité par personne (ses 5 gabarits comptent ensemble), triée de la plus forte à la plus faible."""
    best: dict[uuid.UUID, float] = {}
    for pid, sim in zip(person_ids, similarities.tolist()):
        if sim > best.get(pid, -2.0):
            best[pid] = sim
    return sorted(best.items(), key=lambda item: item[1], reverse=True)


def decide(ranked: list[tuple[uuid.UUID, float]]) -> Match:
    if not ranked:
        return Match(None, 0.0, 0.0, "unknown")
    top_id, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    margin = top - second if len(ranked) > 1 else top
    if top < settings.face_match_threshold:
        return Match(None, round(top, 3), round(margin, 3), "unknown")
    if len(ranked) > 1 and margin < settings.face_match_margin:
        return Match(None, round(top, 3), round(margin, 3), "ambiguous")
    return Match(top_id, round(top, 3), round(margin, 3))


def identify(db: Session, org_id: uuid.UUID, model_name: str, probe: np.ndarray) -> Match:
    entry = _load(db, org_id, model_name)
    if not entry.person_ids:
        return Match(None, 0.0, 0.0, "unknown")
    similarities = entry.matrix @ probe.astype(np.float32)
    return decide(best_matches(entry.person_ids, similarities))
