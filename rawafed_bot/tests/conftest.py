import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test env vars before any app import so settings load them
os.environ["BOT_TOKEN"] = "test_token"
os.environ["CEO_TELEGRAM_ID"] = "111111111"
os.environ["MEMBER_TELEGRAM_IDS"] = "111111111,222222222,333333333,444444444,555555555"
os.environ["ALLOW_ENV_MEMBER_BOOTSTRAP"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///data/test.db"
os.environ["TEST_DATABASE_URL"] = "sqlite:///data/test.db"
os.environ["TIMEZONE"] = "Asia/Damascus"

from rawafed_bot.database.connection import Base, configure_sqlite_engine

TEST_DB_URL = "sqlite:///data/test.db"


@pytest.fixture(scope="function")
def db():
    """Create a fresh database for each test function."""
    os.makedirs("data", exist_ok=True)
    # Use a unique file per test to avoid cross-test contamination
    import uuid
    test_db_path = f"sqlite:///data/test_{uuid.uuid4().hex}.db"
    engine = create_engine(
        test_db_path,
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )
    configure_sqlite_engine(engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()
    # Cleanup test db file
    import pathlib
    db_file = test_db_path.replace("sqlite:///", "")
    pathlib.Path(db_file).unlink(missing_ok=True)
