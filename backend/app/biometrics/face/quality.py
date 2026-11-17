import cv2
import numpy as np

from app.biometrics.face.types import DetectedFace, Issue
from app.config import settings


def assess(image_bgr: np.ndarray, face: DetectedFace) -> tuple[list[Issue], dict[str, float]]:
    """Contrôle la qualité d'une capture : taille, cadrage, lumière, netteté."""
    height, width = image_bgr.shape[:2]
    x, y, w, h = face.box
    metrics: dict[str, float] = {"face_width_px": round(float(w), 1), "det_score": round(float(face.score), 3)}
    issues: list[Issue] = []

    if w < settings.face_min_face_px:
        issues.append(Issue("too_small", "Rapproche-toi de la caméra"))

    margin = 0.02
    if x < -margin * width or y < -margin * height or x + w > width * (1 + margin) or y + h > height * (1 + margin):
        issues.append(Issue("cut_off", "Ton visage dépasse du cadre : recentre-toi"))

    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(width, int(x + w)), min(height, int(y + h))
    if x1 - x0 < 8 or y1 - y0 < 8:
        issues.append(Issue("cut_off", "Ton visage dépasse du cadre : recentre-toi"))
        return issues, metrics

    gray = cv2.cvtColor(image_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)  # même échelle quelle que soit la distance
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    metrics.update(sharpness=round(sharpness, 1), brightness=round(brightness, 1), contrast=round(contrast, 1))

    if brightness < settings.face_min_brightness:
        issues.append(Issue("too_dark", "Trop sombre : place-toi face à la lumière"))
    elif brightness > settings.face_max_brightness:
        issues.append(Issue("too_bright", "Trop de lumière : évite le contre-jour et les reflets"))
    elif contrast < settings.face_min_contrast:
        issues.append(Issue("low_contrast", "Visage peu contrasté : améliore l'éclairage"))
    if sharpness < settings.face_min_sharpness:
        issues.append(Issue("blurry", "Image floue : ne bouge pas et essuie l'objectif"))
    return issues, metrics
