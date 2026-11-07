from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from rawafed_bot.core.config import settings, sqlite_path_from_url

# Ensure persistent data directory exists (e.g. /data on FadeHost)
settings.data_dir.mkdir(parents=True, exist_ok=True)


def configure_sqlite_engine(engine):
    """WAL + busy timeout + BEGIN IMMEDIATE to prevent lost balance updates."""
    if engine.dialect.name != "sqlite":
        return engine

    @event.listens_for(engine, "connect")
    def _sqlite_connect(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn):
        # Replace default deferred BEGIN with immediate write lock.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


_sqlite_args = {"check_same_thread": False, "timeout": 30} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_sqlite_args,
    echo=False,
)
configure_sqlite_engine(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create missing tables / apply additive patches. Never drops existing data."""
    import rawafed_bot.database.models  # noqa: F401

    db_file = sqlite_path_from_url(settings.DATABASE_URL)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    existed = db_file.exists() and db_file.stat().st_size > 0
    if existed:
        try:
            from rawafed_bot.services.backup_service import BackupService
            BackupService.create_backup(note="pre_schema_patch")
        except Exception:
            pass
    Base.metadata.create_all(bind=engine)
    from rawafed_bot.database.migrate import ensure_schema_patches
    ensure_schema_patches()
    return existed


def get_test_engine(database_url: str = None):
    url = database_url or settings.TEST_DATABASE_URL
    if url.startswith("sqlite:///"):
        path = Path(url.replace("sqlite:///", "", 1))
        path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {},
        echo=False,
    )
    return configure_sqlite_engine(eng)
