"""Estimation de l'orientation de la tête à partir de 5 points (yeux, nez, coins de la bouche).

On ajuste un modèle 3D de visage moyen (en millimètres) sur ces points avec solvePnP.
C'est une estimation approximative (quelques degrés d'erreur), suffisante pour vérifier qu'une
personne a bien tourné la tête, pas pour mesurer un angle précis.
"""
import math

import cv2
import numpy as np

from app.biometrics.face.types import Issue, Pose
from app.config import settings

# Repère de la caméra OpenCV : x vers la droite de l'image, y vers le bas, z vers l'avant.
# Visage de face = rotation nulle. Le nez est le point le plus proche de la caméra.
MODEL_POINTS = np.array(
    [
        [-31.5, -42.0, 30.0],  # œil droit du sujet (côté gauche de l'image)
        [31.5, -42.0, 30.0],  # œil gauche du sujet
        [0.0, 0.0, 0.0],  # bout du nez
        [-25.0, 30.0, 24.0],  # coin droit de la bouche
        [25.0, 30.0, 24.0],  # coin gauche de la bouche
    ],
    dtype=np.float64,
)


def _camera_matrix(width: int, height: int) -> np.ndarray:
    focal = float(max(width, height))
    return np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]], dtype=np.float64)


def rotation_matrix(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """R = Rz(roll) · Ry(yaw) · Rx(pitch), angles en degrés."""
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return rz @ ry @ rx


def project_landmarks(pose: Pose, width: int, height: int, distance_mm: float = 400.0) -> np.ndarray:
    """Position à l'écran des 5 points pour une pose donnée (sert aux tests et aux simulations)."""
    rotation = rotation_matrix(pose.yaw, pose.pitch, pose.roll)
    points = (rotation @ MODEL_POINTS.T).T + np.array([0.0, 0.0, distance_mm])
    cam = _camera_matrix(width, height)
    projected = (cam @ points.T).T
    return (projected[:, :2] / projected[:, 2:3]).astype(np.float32)


def estimate_pose(landmarks: np.ndarray, width: int, height: int) -> Pose | None:
    cam = _camera_matrix(width, height)
    points = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    ok, rvec, tvec = cv2.solvePnP(MODEL_POINTS, points, cam, None, flags=cv2.SOLVEPNP_EPNP)
    if not ok:
        return None
    rvec, tvec = cv2.solvePnPRefineLM(MODEL_POINTS, points, cam, None, rvec, tvec)
    if tvec[2, 0] <= 0:  # le visage serait derrière la caméra : solution aberrante
        return None
    rotation, _ = cv2.Rodrigues(rvec)
    sy = math.hypot(rotation[0, 0], rotation[1, 0])
    return Pose(
        yaw=math.degrees(math.atan2(-rotation[2, 0], sy)),
        pitch=math.degrees(math.atan2(rotation[2, 1], rotation[2, 2])),
        roll=math.degrees(math.atan2(rotation[1, 0], rotation[0, 0])),
    )


def pose_issues(name: str, pose: Pose, reference: Pose | None) -> list[Issue]:
    """Vérifie que la pose demandée est bien prise (face / côté / haut / bas), relativement à la pose de face."""
    issues: list[Issue] = []
    if abs(pose.roll) > settings.face_max_roll:
        issues.append(Issue("tilted", "Redresse la tête : elle est penchée sur l'épaule"))
    if name == "front":
        if abs(pose.yaw) > settings.face_front_max_yaw or abs(pose.pitch) > settings.face_front_max_pitch:
            issues.append(Issue("not_frontal", "Regarde droit vers la caméra"))
        return issues
    if reference is None:
        issues.append(Issue("no_reference", "Capture d'abord la pose de face"))
        return issues

    d_yaw, d_pitch = pose.yaw - reference.yaw, pose.pitch - reference.pitch
    if name in ("left", "right"):
        if abs(d_yaw) < settings.face_min_yaw_delta:
            issues.append(Issue("turn_more", "Tourne un peu plus la tête sur le côté"))
        if abs(d_pitch) > 25:
            issues.append(Issue("keep_level", "Garde la tête à la même hauteur"))
    else:
        if abs(d_pitch) < settings.face_min_pitch_delta:
            issues.append(
                Issue("tilt_more", "Relève un peu plus le menton" if name == "up" else "Baisse un peu plus le menton")
            )
        if abs(d_yaw) > 20:
            issues.append(Issue("keep_straight", "Ne tourne pas la tête sur le côté"))
    return issues


def opposite_pose_issues(poses: dict[str, Pose], reference: Pose) -> dict[str, list[Issue]]:
    """Gauche et droite doivent être des côtés opposés ; haut et bas aussi."""
    out: dict[str, list[Issue]] = {}
    pairs = (("left", "right", "yaw", "Tourne la tête de l'autre côté"), ("up", "down", "pitch", "Incline la tête dans l'autre sens"))
    for first, second, axis, message in pairs:
        if first in poses and second in poses:
            a = getattr(poses[first], axis) - getattr(reference, axis)
            b = getattr(poses[second], axis) - getattr(reference, axis)
            if a * b > 0:
                out[second] = [Issue("same_direction", message)]
    return out
