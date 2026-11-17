"""Moteur de reconnaissance faciale : YuNet (détection, licence MIT) + SFace (reconnaissance,
licence Apache 2.0), via OpenCV. Ces deux modèles sont utilisables commercialement.

Les fichiers de modèles (~39 Mo) sont téléchargés au premier démarrage dans FACE_MODELS_DIR
et vérifiés par empreinte SHA-256. On peut aussi les y déposer à la main.
"""
import hashlib
import logging
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.biometrics.face.types import DetectedFace, EngineNotReady, EngineStatus
from app.config import settings

logger = logging.getLogger("pointage.face")

_ZOO = "opencv/opencv_zoo/main/models"


@dataclass(frozen=True)
class ModelFile:
    name: str
    sha256: str
    urls: tuple[str, ...]


YUNET = ModelFile(
    name="face_detection_yunet_2023mar.onnx",
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    urls=(
        f"https://github.com/{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx".replace("/main/", "/raw/main/"),
        f"https://media.githubusercontent.com/media/{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
)
SFACE = ModelFile(
    name="face_recognition_sface_2021dec.onnx",
    sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    urls=(
        f"https://github.com/{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx".replace("/main/", "/raw/main/"),
        f"https://media.githubusercontent.com/media/{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
)


RETRY_DELAY = 1.0  # secondes entre deux essais de téléchargement


class ModelDownloadError(RuntimeError):
    pass


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _download(model: ModelFile, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    errors: list[str] = []
    for url in model.urls:
        for attempt in (1, 2):
            try:
                digest = hashlib.sha256()
                with urllib.request.urlopen(url, timeout=60) as response, open(tmp, "wb") as out:
                    while chunk := response.read(1 << 20):
                        out.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != model.sha256:
                    raise ModelDownloadError("empreinte SHA-256 incorrecte (fichier corrompu ou remplacé)")
                os.replace(tmp, dest)
                return
            except Exception as exc:  # réseau, disque, empreinte...
                errors.append(f"{url} (essai {attempt}) : {exc}")
                tmp.unlink(missing_ok=True)
                time.sleep(RETRY_DELAY)
    raise ModelDownloadError("Téléchargement impossible. " + " | ".join(errors[-2:]))


def ensure_models(directory: Path, models: tuple[ModelFile, ...]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in models:
        path = directory / model.name
        if path.exists():
            if _sha256_of(path) != model.sha256:
                raise ModelDownloadError(
                    f"Le fichier {path} ne correspond pas au modèle attendu. Supprime-le pour le retélécharger."
                )
        else:
            logger.info("Téléchargement du modèle %s", model.name)
            _download(model, path)
        paths.append(path)
    return paths


class OpenCVFaceEngine:
    model_name = "yunet2023mar-sface2021dec"

    def __init__(self, models_dir: str, models: tuple[ModelFile, ModelFile] = (YUNET, SFACE)):
        self._dir = Path(models_dir)
        self._models = models
        self._state = "idle"
        self._error: str | None = None
        self._last_attempt = 0.0
        self._detector = None
        self._recognizer = None
        self._load_lock = threading.Lock()
        self._lock = threading.Lock()  # les modèles OpenCV ne sont pas faits pour être appelés en parallèle

    # ------------------------------------------------------------ chargement
    def start_loading(self) -> None:
        if self._state in ("loading", "ready"):
            return
        threading.Thread(target=self.load, name="face-model-loader", daemon=True).start()

    def load(self) -> None:
        with self._load_lock:
            if self._state == "ready":
                return
            self._state, self._error, self._last_attempt = "loading", None, time.monotonic()
            try:
                import cv2

                det_path, rec_path = ensure_models(self._dir, self._models)
                self._detector = cv2.FaceDetectorYN.create(str(det_path), "", (320, 320), settings.face_det_score, 0.3, 5000)
                self._recognizer = cv2.FaceRecognizerSF.create(str(rec_path), "")
                self._state = "ready"
                logger.info("Moteur de reconnaissance faciale prêt")
            except Exception as exc:
                self._state, self._error = "error", str(exc)
                logger.exception("Chargement du moteur de reconnaissance impossible")

    def status(self) -> EngineStatus:
        return EngineStatus(self._state, self.model_name, self._error, str(self._dir))

    # ------------------------------------------------------------- analyse
    def analyze(self, image_bgr: np.ndarray, *, embed: bool = True) -> list[DetectedFace]:
        if self._state != "ready":
            if self._state in ("idle", "error") and time.monotonic() - self._last_attempt > 30:
                self.start_loading()  # nouvelle tentative, au plus une fois toutes les 30 s
            raise EngineNotReady(
                "Le moteur de reconnaissance charge ses modèles, réessaie dans un instant."
                if self._state != "error"
                else f"Le moteur de reconnaissance n'a pas pu démarrer : {self._error}"
            )
        height, width = image_bgr.shape[:2]
        with self._lock:
            self._detector.setInputSize((width, height))
            _, rows = self._detector.detect(image_bgr)
            if rows is None:
                return []
            faces = [
                DetectedFace(
                    box=(float(r[0]), float(r[1]), float(r[2]), float(r[3])),
                    score=float(r[14]),
                    landmarks=np.asarray(r[4:14], dtype=np.float32).reshape(5, 2),
                )
                for r in rows
            ]
            if embed and len(rows) == 1:
                aligned = self._recognizer.alignCrop(image_bgr, rows[0])
                vector = np.asarray(self._recognizer.feature(aligned), dtype=np.float32).reshape(-1)
                norm = float(np.linalg.norm(vector))
                faces[0].embedding = vector / norm if norm > 0 else vector
        return faces


@lru_cache(maxsize=1)
def get_face_engine() -> OpenCVFaceEngine:
    """Un seul moteur pour tout le processus (les modèles ne se chargent qu'une fois)."""
    return OpenCVFaceEngine(settings.face_models_dir)
