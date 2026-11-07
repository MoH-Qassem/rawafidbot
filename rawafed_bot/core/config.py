import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Load .env from project root (local dev only — never ship secrets)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


def resolve_database_url(
    db_path: Optional[str] = None,
    database_url: Optional[str] = None,
) -> str:
    """Prefer DB_PATH (filesystem path) over DATABASE_URL.

    Examples:
      DB_PATH=/data/rawafed.db  → sqlite:////data/rawafed.db
      DB_PATH=D:/data/rawafed.db → sqlite:///D:/data/rawafed.db

    Important: do not re-parse Unix absolute paths via pathlib on Windows
    (Path('/data/x') would become 'D:/data/x').
    """
    raw_path = (db_path if db_path is not None else os.getenv("DB_PATH", "")).strip()
    if raw_path:
        expanded = os.path.expanduser(raw_path).replace("\\", "/")
        return f"sqlite:///{expanded}"
    url = (database_url if database_url is not None else os.getenv("DATABASE_URL", "")).strip()
    if url:
        return url
    # Local default (relative); hostings should set DB_PATH=/data/rawafed.db
    return "sqlite:///data/rawafed.db"


def sqlite_path_from_url(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise ValueError(f"Unsupported DATABASE_URL scheme: {url[:32]}")
    raw = url.replace("sqlite:///", "", 1)
    # Relative paths resolve against project root
    if not raw.startswith("/") and not (len(raw) >= 3 and raw[1] == ":"):
        return (BASE_DIR / raw).resolve()
    return Path(raw)


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CEO_TELEGRAM_ID: int = int(os.getenv("CEO_TELEGRAM_ID", "0") or "0")
    # Optional legacy bootstrap list — interactive registration is preferred.
    # Only applied when ALLOW_ENV_MEMBER_BOOTSTRAP=1 (tests). Never wipe production.
    MEMBER_TELEGRAM_IDS: List[int] = [
        int(x.strip()) for x in os.getenv("MEMBER_TELEGRAM_IDS", "").split(",") if x.strip()
    ]
    DATABASE_URL: str = resolve_database_url()
    TEST_DATABASE_URL: str = os.getenv("TEST_DATABASE_URL", "sqlite:///data/test.db")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Damascus")
    WEEKLY_REPORT_DAY: int = int(os.getenv("WEEKLY_REPORT_DAY", "5"))
    WEEKLY_REPORT_HOUR: int = int(os.getenv("WEEKLY_REPORT_HOUR", "18"))
    MONTHLY_REPORT_DAY: int = int(os.getenv("MONTHLY_REPORT_DAY", "1"))
    MONTHLY_REPORT_HOUR: int = int(os.getenv("MONTHLY_REPORT_HOUR", "9"))
    MAX_MEMBERS: int = int(os.getenv("MAX_MEMBERS", "5"))

    @property
    def ALLOW_ENV_MEMBER_BOOTSTRAP(self) -> bool:
        """Read live from env so tests can toggle without reimport."""
        return os.getenv("ALLOW_ENV_MEMBER_BOOTSTRAP", "0").strip() in {
            "1", "true", "True", "yes", "YES",
        }

    @property
    def LOG_LEVEL(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def BUILD_ID_ENV(self) -> str:
        return os.getenv("BUILD_ID", "").strip()

    @property
    def db_path(self) -> Path:
        return sqlite_path_from_url(self.DATABASE_URL)

    @property
    def data_dir(self) -> Path:
        """Persistent data directory (parent of the SQLite file)."""
        return self.db_path.parent

    @property
    def effective_build_id(self) -> str:
        from rawafed_bot.core.version import CODE_BUILD_ID
        return self.BUILD_ID_ENV or CODE_BUILD_ID

    @property
    def all_authorized_ids(self) -> List[int]:
        """Legacy helper: CEO + optional MEMBER_TELEGRAM_IDS from env."""
        ids = set(self.MEMBER_TELEGRAM_IDS)
        if self.CEO_TELEGRAM_ID:
            ids.add(self.CEO_TELEGRAM_ID)
        return sorted(ids)

    @property
    def is_valid(self) -> bool:
        # Members beyond CEO are registered interactively — do not require 5 env IDs.
        return bool(self.BOT_TOKEN) and self.CEO_TELEGRAM_ID != 0


settings = Settings()
