import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


def ensure_sslmode(url: str) -> str:
    """
    Cloud Postgres like Neon usually needs sslmode=require.
    Local Docker/Postgres should use sslmode=disable.
    If sslmode is already present in DATABASE_URL, respect it.
    """
    if not url.startswith("postgresql"):
        return url

    if "sslmode=" in url:
        return url

    separator = "&" if "?" in url else "?"

    local_hosts = [
        "localhost",
        "127.0.0.1",
        "platformiq-postgres",
    ]

    if any(host in url for host in local_hosts):
        return f"{url}{separator}sslmode=disable"

    return f"{url}{separator}sslmode=require"


DATABASE_URL = ensure_sslmode(DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
    pool_size=5,
    max_overflow=10,
    connect_args={
        "connect_timeout": 10,
    },
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()