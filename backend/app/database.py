import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def normalize_database_url(value: str):
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]

    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]

    return value

DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/muse_ai",
    )
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass
