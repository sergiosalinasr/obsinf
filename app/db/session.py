from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings


settings = get_settings()

engine = create_engine(
    settings.database_url.get_secret_value(),
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)

from collections.abc import Generator
from sqlalchemy.orm import Session


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session