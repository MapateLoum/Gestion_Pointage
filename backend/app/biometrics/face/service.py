import logging
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.biometrics.face import pose as pose_lib
from app.biometrics.face import quality
from app.biometrics.face.types import DetectedFace, FaceEngine, Issue, Pose
from app.config import settings
from app.core import crypto
from app.models import FaceTemplate, Person

logger = logging.getLogger("pointage.face")

POSES = ("front", "left", "right", "up", "down")


@dataclass
class FrameAnalysis:
    face_count: int
    issues: list[Issue] = field(default_factory=list)
    pose: Pose | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    face: DetectedFace | None = None

    @property
    def ok(self) -> bool:
        return self.face_count == 1 and not self.issues


def analyze_frame(
    engine: FaceEngine,
    image: np.ndarray,
    pose_name: str,
    reference: Pose | None,
    *,
    embed: bool = False,
    check_relative: bool = True,
) -> FrameAnalysis:
    faces = engine.analyze(image, embed=embed)
    if not faces:
        return FrameAnalysis(0, [Issue("no_face", "Aucun visage détecté : place-toi face à la caméra")])
    if len(faces) > 1:
        return FrameAnalysis(len(faces), [Issue("multiple_faces", "Un seul visage doit être visible")])

    face = faces[0]
    issues, metrics = quality.assess(image, face)
    height, width = image.shape[:2]
    pose = pose_lib.estimate_pose(face.landmarks, width, height)
    if pose is None:
        issues.append(Issue("pose_unknown", "Orientation du visage non détectée : regarde la caméra"))
    elif settings.face_enforce_poses:
        if pose_name == "front" or check_relative:
            issues.extend(pose_lib.pose_issues(pose_name, pose, reference))
    return FrameAnalysis(1, issues, pose, metrics, face)


# ----------------------------------------------------------------------------- enrôlement

class EnrollmentRejected(Exception):
    def __init__(self, by_pose: dict[str, list[Issue]]):
        super().__init__("captures refusées")
        self.by_pose = by_pose


@dataclass
class DuplicateFound(Exception):
    person_id: uuid.UUID
    matricule: str
    name: str
    similarity: float


@dataclass
class EnrollmentResult:
    templates: int
    poses: list[str]
    average_quality: float


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # vecteurs déjà normalisés


def find_duplicate(
    db: Session, org_id: uuid.UUID, person_id: uuid.UUID, model_name: str, embeddings: list[np.ndarray]
) -> DuplicateFound | None:
    """Cherche, dans la MÊME organisation, une autre personne dont le visage ressemble trop à celui-ci."""
    rows = db.execute(
        select(FaceTemplate.person_id, FaceTemplate.pose, FaceTemplate.embedding).where(
            FaceTemplate.organisation_id == org_id,
            FaceTemplate.person_id != person_id,
            FaceTemplate.model_name == model_name,
        )
    ).all()
    if not rows:
        return None
    owners = [r.person_id for r in rows]
    matrix = np.stack(
        [crypto.decrypt_embedding(r.embedding, crypto.template_aad(org_id, r.person_id, r.pose)) for r in rows]
    )
    sims = np.stack(embeddings) @ matrix.T  # (captures, gabarits existants)
    capture_idx, template_idx = np.unravel_index(int(np.argmax(sims)), sims.shape)
    best = float(sims[capture_idx, template_idx])
    if best < settings.face_duplicate_threshold:
        return None
    owner = db.execute(
        select(Person.id, Person.matricule, Person.first_name, Person.last_name).where(Person.id == owners[template_idx])
    ).one()
    return DuplicateFound(owner.id, owner.matricule, f"{owner.first_name} {owner.last_name}", round(best, 3))


def enroll(
    db: Session, engine: FaceEngine, person: Person, images: dict[str, np.ndarray]
) -> EnrollmentResult:
    """Valide les 5 captures puis remplace les gabarits de la personne. Ne fait pas le commit."""
    org_id = person.organisation_id
    crypto.ensure_configured()

    analyses: dict[str, FrameAnalysis] = {}
    analyses["front"] = analyze_frame(engine, images["front"], "front", None, embed=True)
    front_pose = analyses["front"].pose if analyses["front"].ok else None
    for name in POSES[1:]:
        analyses[name] = analyze_frame(
            engine, images[name], name, front_pose, embed=True, check_relative=front_pose is not None
        )

    problems: dict[str, list[Issue]] = {n: list(a.issues) for n, a in analyses.items() if a.issues}
    if front_pose is None:
        for name in POSES[1:]:
            problems.setdefault(name, [])
    if problems:
        raise EnrollmentRejected(problems)

    if settings.face_enforce_poses and front_pose is not None:
        poses = {n: a.pose for n, a in analyses.items() if a.pose is not None}
        opposite = pose_lib.opposite_pose_issues(poses, front_pose)
        if opposite:
            raise EnrollmentRejected(opposite)

    embeddings = {n: a.face.embedding for n, a in analyses.items() if a.face and a.face.embedding is not None}
    if len(embeddings) != len(POSES):
        raise EnrollmentRejected({"front": [Issue("no_embedding", "Visage non exploitable, recommence la capture")]})

    # Les 5 captures doivent montrer la même personne.
    mismatched = {
        name: [Issue("different_person", "Cette capture ne ressemble pas à la pose de face")]
        for name in POSES[1:]
        if _cosine(embeddings["front"], embeddings[name]) < settings.face_consistency_threshold
    }
    if mismatched:
        raise EnrollmentRejected(mismatched)

    duplicate = find_duplicate(db, org_id, person.id, engine.model_name, [embeddings[n] for n in POSES])
    if duplicate:
        raise duplicate

    db.execute(delete(FaceTemplate).where(FaceTemplate.person_id == person.id))
    for name in POSES:
        db.add(
            FaceTemplate(
                organisation_id=org_id,
                person_id=person.id,
                pose=name,
                embedding=crypto.encrypt_embedding(embeddings[name], crypto.template_aad(org_id, person.id, name)),
                model_name=engine.model_name,
                quality_score=float(analyses[name].face.score),  # type: ignore[union-attr]
            )
        )
    average = float(np.mean([a.face.score for a in analyses.values()]))  # type: ignore[union-attr]
    return EnrollmentResult(len(POSES), list(POSES), round(average, 3))
