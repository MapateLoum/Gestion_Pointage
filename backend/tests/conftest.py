import os

# Les tests n'ont besoin ni de PostgreSQL ni de Redis réels.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "cle-de-test-uniquement-0123456789-abcdefghijklmnop")
os.environ["FACE_PRELOAD"] = "false"  # ne jamais télécharger de modèles pendant les tests
os.environ["FACE_ENCRYPTION_KEY"] = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="  # clé de test (32 octets)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@pytest.fixture
def db_session():
    from app.models import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        # SQLite ignore les clés étrangères par défaut ; PostgreSQL non.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def face_engine():
    from tests.fakes import FakeEngine

    return FakeEngine()


@pytest.fixture
def client(db_session, face_engine):
    from app.biometrics.face.engine import get_face_engine
    from app.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_face_engine] = lambda: face_engine
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
