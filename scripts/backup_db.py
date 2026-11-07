"""Create a local SQLite backup. Usage: python scripts/backup_db.py"""
from rawafed_bot.services.backup_service import BackupService


def main():
    path = BackupService.create_backup("cli")
    print(f"Backup created: {path}")


if __name__ == "__main__":
    main()
