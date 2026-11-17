from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Organisation


def test_organisation_defaults():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Organisation(name="École Test"))
        session.commit()
        org = session.scalar(select(Organisation))

    assert org is not None
    assert org.id is not None
    assert org.country == "SN"
    assert org.status == "active"
    assert org.created_at is not None
