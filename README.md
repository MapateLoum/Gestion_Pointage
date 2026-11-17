# Pointage biométrique (visage + empreinte)

Plateforme de pointage de présence pour écoles, entreprises et chantiers.
Back : FastAPI + PostgreSQL + Redis. Front : Next.js. Visage : OpenCV (YuNet + SFace). Empreinte : WebAuthn.

## Démarrage rapide (Windows, Docker Desktop lancé)

1. Copie `.env.example` en `.env` puis remplis :
   - `POSTGRES_PASSWORD` et le même mot de passe dans `DATABASE_URL` (lettres et chiffres seulement)
   - `SECRET_KEY` et `FACE_ENCRYPTION_KEY` : une valeur aléatoire chacune
     ```
     docker run --rm python:3.11-slim python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
     ```
   - **Sauvegarde `FACE_ENCRYPTION_KEY` ailleurs** : sans elle, les visages enrôlés sont illisibles.
2. Lance : `docker compose up --build`
3. Dans un second terminal :
   ```
   docker compose exec api alembic revision --autogenerate -m "init"
   docker compose exec api alembic upgrade head
   docker compose exec api python -m app.scripts.create_super_admin --email toi@exemple.com --full-name "Ton Nom"
   ```
4. Ouvre http://localhost:3000 (pas 127.0.0.1 : l'empreinte WebAuthn l'exige).

Tests : `docker compose exec api pytest`

## Adresses
- Site : http://localhost:3000
- API et documentation : http://localhost:8000/docs

## Notes
- Les modèles de reconnaissance (~40 Mo) se téléchargent au premier démarrage dans le dossier `models/`.
- Le texte de consentement (`backend/app/biometrics/consent.py`) est un modèle à faire relire par un juriste avant toute mise en production.
- Les fichiers de migration (`backend/alembic/versions/`) ne sont pas dans l'archive : génère-les avec la commande de l'étape 3.
