"""Reversal / cancel keeps audit trail."""
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import Account, AuditLog, Transaction
from rawafed_bot.services.operation_service import OperationService


class TestReversal:
    def test_reverse_deposit_restores_cash(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        tx = OperationService.record_deposit(
            db=db, amount=800, currency_id=currency_id, member_id=member.id,
            description="للإلغاء", created_by=member.id,
        )
        db.refresh(cash)
        assert cash.balance == 800
        OperationService.reverse_transaction(
            db=db, transaction_id=tx.id, reason="خطأ إدخال", created_by=member.id,
        )
        db.refresh(cash)
        db.refresh(tx)
        assert cash.balance == 0
        assert tx.status == "reversed"
        audits = db.query(AuditLog).filter_by(action="reverse").all()
        assert len(audits) >= 1
        assert db.query(Transaction).filter_by(transaction_type="reversal").count() >= 1
