"""Détection de vivacité par défi aléatoire : « regarde devant, puis tourne la tête à gauche, puis lève le menton ».

Une photo ou une capture d'écran immobile ne peut pas répondre. Le défi est tiré au hasard, à usage unique et expire
en quelques secondes : une vidéo enregistrée à l'avance ne correspond presque jamais.
ATTENTION : ce n'est PAS une protection complète. Une vidéo diffusée en direct, ou un masque, peuvent encore tromper
ce test ; un modèle anti-usurpation dédié ou une caméra infrarouge seront nécessaires pour un déploiement sensible.

Conventions (angles de pose.py) : yaw > 0 = la personne tourne la tête vers SA droite ; pitch < 0 = elle lève le menton.
"""
import random
from dataclasses import dataclass, field

import numpy as np

from app.biometrics.face import quality
from app.biometrics.face.types import DetectedFace, Issue, Pose
from app.config import settings

STEPS = ("left", "right", "up", "down")
INSTRUCTIONS = {
    "left": "Tourne la tête vers ta gauche",
    "right": "Tourne la tête vers ta droite",
    "up": "Lève le menton",
    "down": "Baisse le menton",
}


def new_steps(count: int = 2, rng: random.Random | None = None) -> list[str]:
    """Deux mouvements différents, dans un ordre aléatoire (12 combinaisons possibles)."""
    return (rng or random.SystemRandom()).sample(STEPS, count)


@dataclass
class FrameInfo:
    face_count: int
    face: DetectedFace | None = None
    pose: Pose | None = None
    image: np.ndarray | None = None


@dataclass
class LivenessOutcome:
    ok: bool
    reason: str | None = None
    message: str | None = None
    probe: np.ndarray | None = None  # empreinte moyenne du visage de face, pour la reconnaissance
    details: dict = field(default_factory=dict)


def _fail(reason: str, message: str, **details) -> LivenessOutcome:
    return LivenessOutcome(False, reason, message, details=details)


def _is_frontal(pose: Pose) -> bool:
    return abs(pose.yaw) <= settings.face_front_max_yaw and abs(pose.pitch) <= settings.face_front_max_pitch


def _reached(step: str, pose: Pose, base: Pose) -> bool:
    d_yaw = (pose.yaw - base.yaw) * (-1.0 if settings.face_liveness_flip_yaw else 1.0)
    d_pitch = (pose.pitch - base.pitch) * (-1.0 if settings.face_liveness_flip_pitch else 1.0)
    if step == "left":
        return d_yaw <= -settings.face_liveness_yaw_delta
    if step == "right":
        return d_yaw >= settings.face_liveness_yaw_delta
    if step == "up":
        return d_pitch <= -settings.face_liveness_pitch_delta
    return d_pitch >= settings.face_liveness_pitch_delta  # down


def evaluate(frames: list[FrameInfo], steps: list[str]) -> LivenessOutcome:
    # Un passant quelques instants derrière la personne est toléré (ces images sont ignorées) ;
    # plusieurs visages sur une bonne part de la séquence, non.
    crowded = sum(1 for f in frames if f.face_count > 1)
    if crowded >= max(2, int(len(frames) * 0.3)):
        return _fail("several_faces", "Plusieurs visages détectés : une seule personne devant la caméra")
    valid = [(i, f) for i, f in enumerate(frames) if f.face_count == 1 and f.face and f.pose]
    if not frames or len(valid) < max(4, int(len(frames) * settings.face_liveness_min_valid_ratio)):
        return _fail("no_continuous_face", "Visage non détecté en continu : reste seul face à la caméra", valid=len(valid), total=len(frames))

    # 1. Identité stable : c'est la même personne du début à la fin.
    embeddings = [f.face.embedding for _, f in valid if f.face.embedding is not None]
    if len(embeddings) < 3:
        return _fail("no_embedding", "Visage non exploitable, réessaie")
    reference = np.mean(embeddings[: max(3, len(embeddings) // 3)], axis=0)
    reference /= np.linalg.norm(reference) or 1.0
    lowest = min(float(np.dot(reference, e)) for e in embeddings)
    if lowest < settings.face_consistency_threshold:
        return _fail("identity_changed", "Le visage a changé pendant le test", lowest_similarity=round(lowest, 3))

    # 2. Départ de face : sert de point de repère pour mesurer les mouvements.
    head = valid[: max(3, len(valid) // 3)]
    frontal = [(i, f) for i, f in head if _is_frontal(f.pose)]
    if len(frontal) < 2:
        return _fail("not_frontal_start", "Regarde droit devant la caméra au début")
    base = Pose(
        yaw=float(np.median([f.pose.yaw for _, f in frontal])),
        pitch=float(np.median([f.pose.pitch for _, f in frontal])),
        roll=float(np.median([f.pose.roll for _, f in frontal])),
    )

    # 3. Les mouvements demandés, dans l'ordre demandé.
    cursor = max(i for i, _ in frontal) + 1
    reached: list[str] = []
    for step in steps:
        hit = next((i for i, f in valid if i >= cursor and _reached(step, f.pose, base)), None)
        if hit is None:
            return _fail(f"movement_missing:{step}", f"Mouvement non détecté : {INSTRUCTIONS[step].lower()}", reached=reached)
        reached.append(step)
        cursor = hit + 1

    # 4. Image de qualité suffisante pour reconnaître le visage (images de face du début).
    sharp = []
    problems: list[Issue] = []
    for _, f in frontal:
        issues, _metrics = quality.assess(f.image, f.face) if f.image is not None else ([], {})
        issues = [i for i in issues if i.code != "too_small"]
        if f.face.box[2] < settings.face_kiosk_min_face_px:
            issues.append(Issue("too_small", "Rapproche-toi de la caméra"))
        if issues:
            problems.extend(issues)
        else:
            sharp.append(f)
    if not sharp:
        return _fail("poor_quality", problems[0].message if problems else "Qualité d'image insuffisante", issues=[p.code for p in problems])

    probe = np.mean([f.face.embedding for f in sharp if f.face.embedding is not None], axis=0)
    probe /= np.linalg.norm(probe) or 1.0
    return LivenessOutcome(True, probe=probe, details={"steps": steps, "reached": reached, "frames": len(frames), "valid": len(valid)})
