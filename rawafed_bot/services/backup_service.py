"""SQLite backup and restore helpers."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from rawafed_bot.core.config import settings, BASE_DIR


class BackupError(Exception):
    pass


class BackupService:
    @staticmethod
    def _db_path() -> Path:
        url = settings.DATABASE_URL
        if not url.startswith("sqlite:///"):
            raise BackupError("النسخ الاحتياطي مدعوم حالياً لـ SQLite فقط.")
        path = Path(url.replace("sqlite:///", "", 1))
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    @staticmethod
    def backups_dir() -> Path:
        # Prefer persistent data volume (e.g. /data/backups on FadeHost)
        path = settings.data_dir / "backups"
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            path = BASE_DIR / "backups"
            path.mkdir(parents=True, exist_ok=True)
            return path

    @staticmethod
    def create_backup(note: str = None, label: str = None) -> Path:
        tag = note or label
        src = BackupService._db_path()
        if not src.exists():
            raise BackupError("ملف قاعدة البيانات غير موجود.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{tag}" if tag else ""
        dest = BackupService.backups_dir() / f"rawafed_backup_{stamp}{suffix}.db"
        shutil.copy2(src, dest)
        return dest

    @staticmethod
    def list_backups() -> list:
        return sorted(BackupService.backups_dir().glob("rawafed_backup_*.db"), reverse=True)

    @staticmethod
    def restore_backup(backup_path: Path) -> Path:
        """Restore a backup over the current DB. Stop the bot before calling."""
        src = Path(backup_path)
        if not src.exists():
            raise BackupError("ملف النسخة الاحتياطية غير موجود.")
        dest = BackupService._db_path()
        if dest.exists():
            safety = BackupService.backups_dir() / (
                f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            shutil.copy2(dest, safety)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest
