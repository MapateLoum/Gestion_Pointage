from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class Pose:
    """Angles de la tête en degrés (estimés à partir des 5 points du visage)."""

    yaw: float
    pitch: float
    roll: float


@dataclass
class DetectedFace:
    box: tuple[float, float, float, float]  # x, y, largeur, hauteur (pixels)
    score: float
    landmarks: np.ndarray  # (5, 2) : œil droit, œil gauche, nez, coin droit et gauche de la bouche
    embedding: np.ndarray | None = None  # vecteur normalisé (norme 1)


@dataclass
class EngineStatus:
    state: str  # "idle" | "loading" | "ready" | "error"
    model_name: str
    error: str | None = None
    models_dir: str | None = None


class EngineNotReady(RuntimeError):
    pass


class FaceEngine(Protocol):
    model_name: str

    def analyze(self, image_bgr: np.ndarray, *, embed: bool = True) -> list[DetectedFace]: ...

    def status(self) -> EngineStatus: ...
