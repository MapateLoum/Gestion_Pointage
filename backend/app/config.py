from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://pointage:change-me-db@db:5432/pointage"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "change-me-long-random-string"
    cors_origins: str = "http://localhost:3000"

    # Authentification
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Biométrie du visage
    face_encryption_key: str = ""  # 32 octets en base64 ; sans elle, aucun enrôlement n'est possible
    face_models_dir: str = "/models"
    face_preload: bool = True
    face_det_score: float = 0.6
    face_min_face_px: int = 90
    face_min_sharpness: float = 40.0
    face_min_brightness: float = 60.0
    face_max_brightness: float = 205.0
    face_min_contrast: float = 20.0
    face_max_roll: float = 25.0
    face_front_max_yaw: float = 15.0
    face_front_max_pitch: float = 20.0
    face_min_yaw_delta: float = 12.0
    face_min_pitch_delta: float = 8.0
    face_enforce_poses: bool = True
    face_duplicate_threshold: float = 0.55
    face_consistency_threshold: float = 0.30
    face_max_image_bytes: int = 1_500_000
    face_max_image_pixels: int = 12_000_000

    # Empreinte digitale (WebAuthn / Windows Hello). L'identifiant et l'origine doivent correspondre
    # EXACTEMENT à l'adresse du site dans le navigateur (localhost et 127.0.0.1 ne sont pas équivalents).
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Pointage biométrique"
    webauthn_origins: str = "http://localhost:3000"
    webauthn_challenge_ttl_seconds: int = 300
    max_fingerprints_per_person: int = 3

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def webauthn_origins_list(self) -> list[str]:
        return [o.strip() for o in self.webauthn_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _refuse_default_secret_in_production(self) -> "Settings":
        if self.env == "production" and self.secret_key.startswith("change-me"):
            raise ValueError("SECRET_KEY doit être changée en production")
        return self


settings = Settings()
