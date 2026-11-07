"""Reports and backup tests."""
from pathlib import Path

from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import Account
from rawafed_bot.services.operation_service import OperationService
from rawafed_bot.services.backup_service import BackupService
from rawafed_bot.reports.generator import ReportGenerator
from rawafed_bot.utils.money import format_amount, parse_user_amount, find_currency


class TestReportsBackup:
    def test_excel_export_creates_file(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        OperationService.record_deposit(
            db=db, amount=2500, currency_id=currency_id, member_id=member.id,
            description="إيداع تقرير", created_by=member.id,
        )
        path = ReportGenerator.export_period_excel(db, title="اختبار_تقرير")
        assert path.exists()
        assert path.suffix == ".xlsx"
        path.unlink(missing_ok=True)

    def test_cash_box_text(self, db):
        seed_all(db)
        text = ReportGenerator.cash_box_text(db)
        assert "حالة الصندوق" in text
        assert "USD" in text

    def test_backup_create_and_list(self, db, tmp_path, monkeypatch):
        seed_all(db)
        import rawafed_bot.services.backup_service as bs

        fake_db = tmp_path / "rawafed.db"
        fake_db.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

        monkeypatch.setattr(bs, "BASE_DIR", tmp_path)
        monkeypatch.setattr(bs.settings, "DATABASE_URL", f"sqlite:///{fake_db.as_posix()}")

        dest = BackupService.create_backup(note="test")
        assert dest.exists()
        assert dest.parent == tmp_path / "backups"
        assert BackupService.list_backups()
        restored = BackupService.restore_backup(dest)
        assert restored.exists()

    def test_money_parse_and_find(self, db):
        seed_all(db)
        cur = find_currency(db, "دولار")
        assert cur is not None
        assert cur.code == "USD"
        minor = parse_user_amount("10.50", cur)
        assert minor == 1050
        assert "10.50" in format_amount(minor, cur)
