from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audit, auth, biometrics, fingerprint, health, organisations, persons, structure, users
from app.biometrics.face.engine import get_face_engine
from app.config import settings

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.face_preload:
        get_face_engine().start_loading()  # charge (et au besoin télécharge) les modèles en tâche de fond
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Pointage biométrique API",
    version="0.6.0",
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(organisations.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(structure.sites_router)
app.include_router(structure.departments_router)
app.include_router(structure.groups_router)
app.include_router(persons.router)
app.include_router(biometrics.router)
app.include_router(fingerprint.router)
