"""Faux moteur de reconnaissance pour les tests : aucun modèle à télécharger.

Chaque image de test est un PNG (sans perte) de bruit dont les deux premiers pixels portent
une « étiquette » lue par le faux moteur : identité, type de scénario et pose de la tête.
Le contrôle de qualité (netteté, lumière...) et l'estimation de pose tournent pour de vrai.
"""
import base64

import cv2
import numpy as np

from app.biometrics.face.pose import project_landmarks
from app.biometrics.face.types import DetectedFace, EngineNotReady, EngineStatus, Pose

W, H = 320, 240
FLAGS = {"ok": 1, "blurry": 1, "dark": 1, "noface": 0, "two": 2, "small": 3, "cutoff": 4}

# Poses d'un enrôlement réussi (degrés)
GOOD_POSES = {
    "front": (0, 0),
    "left": (-25, 0),
    "right": (25, 0),
    "up": (0, -15),
    "down": (0, 15),
}


def make_image(identity: int = 1, yaw: float = 0, pitch: float = 0, roll: float = 0, kind: str = "ok") -> str:
    img = np.random.default_rng(1234).integers(10, 245, size=(H, W, 3), dtype=np.uint8)
    if kind == "blurry":
        img[:] = 128
    elif kind == "dark":
        img = (img * 0.15).astype(np.uint8)
    img[0, 0] = (identity, FLAGS[kind], 0)
    img[0, 1] = (round(yaw) + 128, round(pitch) + 128, round(roll) + 128)
    ok, png = cv2.imencode(".png", img)
    assert ok
    return "data:image/png;base64," + base64.b64encode(png.tobytes()).decode()


def capture_set(identity: int = 1, **overrides) -> list[dict]:
    """5 captures valides d'une même personne. overrides : pose -> kwargs de make_image."""
    images = []
    for pose, (yaw, pitch) in GOOD_POSES.items():
        kwargs = {"identity": identity, "yaw": yaw, "pitch": pitch, **overrides.get(pose, {})}
        images.append({"pose": pose, "image": make_image(**kwargs)})
    return images


def embedding_for(identity: int, yaw: int = 0, pitch: int = 0) -> np.ndarray:
    base = np.random.default_rng(identity).normal(size=128)
    base /= np.linalg.norm(base)
    noise = np.random.default_rng(identity * 100_000 + yaw * 100 + pitch + 50_000).normal(size=128) * 0.05
    vec = base + noise
    return (vec / np.linalg.norm(vec)).astype(np.float32)


class FakeEngine:
    model_name = "fake"

    def __init__(self, ready: bool = True):
        self.ready = ready

    def status(self) -> EngineStatus:
        return EngineStatus("ready" if self.ready else "loading", self.model_name)

    def analyze(self, image_bgr, *, embed: bool = True):
        if not self.ready:
            raise EngineNotReady("Le moteur de reconnaissance charge ses modèles, réessaie dans un instant.")
        identity, flag, _ = (int(v) for v in image_bgr[0, 0])
        yaw, pitch, roll = (int(v) - 128 for v in image_bgr[0, 1])
        height, width = image_bgr.shape[:2]
        if flag == 0:
            return []
        landmarks = project_landmarks(Pose(yaw, pitch, roll), width, height)
        boxes = {1: (64.0, 36.0, 192.0, 168.0), 2: (64.0, 36.0, 192.0, 168.0), 3: (140.0, 100.0, 40.0, 40.0), 4: (-30.0, 36.0, 192.0, 168.0)}
        faces = [DetectedFace(box=boxes[flag], score=0.95, landmarks=landmarks)]
        if flag == 2:
            faces.append(DetectedFace(box=(10.0, 10.0, 60.0, 60.0), score=0.9, landmarks=landmarks))
        if embed and len(faces) == 1:
            faces[0].embedding = embedding_for(identity, yaw, pitch)
        return faces
