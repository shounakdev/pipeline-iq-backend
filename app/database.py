import os
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")


def ensure_sslmode(url: str) -> str:
    """
    Cloud Postgres usually needs sslmode=require.
    Local Docker/Postgres should use sslmode=disable.
    If sslmode is already present in DATABASE_URL, respect it.
    """

    if not url.startswith("postgresql"):
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))

    if "sslmode" in query:
        return url

    local_hosts = {
        "localhost",
        "127.0.0.1",
        "postgres",
        "cicd_postgres",
        "platformiq-postgres",
        "host.docker.internal",
    }

    if parsed.hostname in local_hosts:
        query["sslmode"] = "disable"
    else:
        query["sslmode"] = "require"

    new_query = urlencode(query)

    return urlunparse(parsed._replace(query=new_query))


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