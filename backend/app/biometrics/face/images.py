import base64
import binascii
import io

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.config import settings

MAX_SIDE = 960  # on travaille sur des images réduites : plus rapide, et suffisant pour un visage
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def load_image(data: str) -> np.ndarray:
    """Décode une image envoyée par le navigateur (data URL ou base64) en tableau BGR."""
    payload = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("bad_encoding", "Image illisible (encodage invalide)")
    if len(raw) > settings.face_max_image_bytes:
        raise ImageError("too_large", "Image trop volumineuse")
    try:
        with Image.open(io.BytesIO(raw)) as probe:  # lit seulement l'en-tête : protège des « bombes » d'images
            fmt, (width, height) = probe.format, probe.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("not_image", "Le fichier n'est pas une image valide")
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("bad_format", "Format d'image non accepté (JPEG, PNG ou WebP)")
    if width * height > settings.face_max_image_pixels:
        raise ImageError("too_many_pixels", "Image trop grande")

    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ImageError("not_image", "Le fichier n'est pas une image valide")
    longest = max(image.shape[:2])
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image
