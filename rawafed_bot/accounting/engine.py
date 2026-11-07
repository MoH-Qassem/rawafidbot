"""Double-Entry Accounting Engine for Rawafed Bot.

All financial operations MUST pass through this engine.
Never modify account balances directly outside this engine.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.journal import JournalEntry, JournalLine
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.utils.idempotency import generate_uuid


class AccountingError(Exception):
    """Raised when an accounting rule is violated."""
    pass


class JournalLineData:
    def __init__(self, account_id: int, debit: int = 0, credit: int = 0, description: str = None):
        if debit < 0 or credit < 0:
            raise AccountingError("المبالغ يجب أن تكون موجبة.")
        if debit > 0 and credit > 0:
            raise AccountingError("لا يمكن أن يكون الحساب مديناً ودائناً في نفس الوقت.")
        self.account_id = account_id
        self.debit = debit
        self.credit = credit
        self.description = description


class AccountingEngine:
    @staticmethod
    def get_account(db: Session, account_type: str, currency_id: int, member_id: int = None) -> Optional[Account]:
        return db.query(Account).filter_by(
            account_type=account_type,
            currency_id=currency_id,
            member_id=member_id,
        ).first()

    @staticmethod
    def get_journal_entry_by_idempotency(db: Session, key: str) -> Optional[JournalEntry]:
        if not key:
            return None
        entry = db.query(JournalEntry).filter_by(idempotency_key=key).first()
        if entry:
            return entry
        tx = db.query(Transaction).filter_by(idempotency_key=key).first()
        if tx:
            return db.query(JournalEntry).filter_by(transaction_id=tx.id).first()
        return None

    @staticmethod
    def _validate_entry(currency_id: int, lines: List[JournalLineData]) -> None:
        total_debit = sum(line.debit for line in lines)
        total_credit = sum(line.credit for line in lines)

        if total_debit != total_credit:
            raise AccountingError(
                f"القيد غير متوازن: المدين ({total_debit}) ≠ الدائن ({total_credit})."
            )

        if total_debit == 0:
            raise AccountingError("لا يمكن إنشاء قيد بمبلغ صفر.")

        if not lines:
            raise AccountingError("القيد فارغ.")

        account_ids = [line.account_id for line in lines]
        if len(account_ids) != len(set(account_ids)):
            raise AccountingError("لا يمكن استخدام نفس الحساب أكثر من مرة في القيد الواحد.")

    @staticmethod
    def _check_currency_consistency(db: Session, currency_id: int, lines: List[JournalLineData]) -> None:
        for line in lines:
            account = db.query(Account).filter_by(id=line.account_id).first()
            if not account:
                raise AccountingError(f"الحساب {line.account_id} غير موجود.")
            if account.currency_id != currency_id:
                raise AccountingError(
                    f"اختلاف العملات في القيد الواحد غير مسموح به."
                )

    @staticmethod
    def _update_balances(db: Session, lines: List[JournalLineData]) -> None:
        for line in lines:
            account = db.query(Account).filter_by(id=line.account_id).with_for_update().first()
            if not account:
                raise AccountingError(f"الحساب {line.account_id} غير موجود أثناء التحديث.")
            account.balance += line.debit - line.credit
            db.add(account)

    @staticmethod
    def create_journal_entry(
        db: Session,
        currency_id: int,
        description: str,
        created_by: int,
        lines: List[JournalLineData],
        transaction_id: int = None,
        idempotency_key: str = None,
        reference_type: str = None,
        reference_id: int = None,
    ) -> JournalEntry:
        """Create a balanced journal entry atomically."""
        if idempotency_key:
            existing = AccountingEngine.get_journal_entry_by_idempotency(db, idempotency_key)
            if existing:
                raise AccountingError("⚠️ هذه العملية تم تسجيلها مسبقاً. لا يمكن تكرارها.")

        AccountingEngine._validate_entry(currency_id, lines)
        AccountingEngine._check_currency_consistency(db, currency_id, lines)
        # Cash box may go negative (overdraft allowed by business rule).

        entry_number = f"JE-{generate_uuid()[:8].upper()}"

        entry = JournalEntry(
            entry_number=entry_number,
            transaction_id=transaction_id,
            reference_type=reference_type,
            reference_id=reference_id,
            currency_id=currency_id,
            description=description,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        db.add(entry)
        db.flush()

        for line in lines:
            jl = JournalLine(
                journal_entry_id=entry.id,
                account_id=line.account_id,
                debit=line.debit,
                credit=line.credit,
                description=line.description,
            )
            db.add(jl)

        AccountingEngine._update_balances(db, lines)

        audit = AuditLog(
            action="create",
            entity_type="journal_entry",
            entity_id=entry.id,
            member_id=created_by,
            new_values=f"entry_number={entry_number}, currency_id={currency_id}, description={description}",
        )
        db.add(audit)

        return entry

    @staticmethod
    def reverse_journal_entry(
        db: Session,
        journal_entry_id: int,
        reason: str,
        created_by: int,
        idempotency_key: str = None,
    ) -> JournalEntry:
        """Create a reversal entry for an existing journal entry."""
        original = db.query(JournalEntry).filter_by(id=journal_entry_id).first()
        if not original:
            raise AccountingError("القيد الأصلي غير موجود.")

        already = db.query(JournalEntry).filter_by(
            reference_type="reversal",
            reference_id=original.id,
        ).first()
        if already:
            raise AccountingError("تم عكس هذا القيد مسبقاً. لا يمكن عكسه مرة أخرى.")

        if original.reference_type == "reversal":
            raise AccountingError("لا يمكن عكس قيد عكسي مباشرة. استخدم العملية الأصلية.")

        original_lines = db.query(JournalLine).filter_by(journal_entry_id=original.id).all()
        if not original_lines:
            raise AccountingError("القيد الأصلي لا يحتوي على بنود.")

        reversal_lines = []
        for line in original_lines:
            reversal_lines.append(JournalLineData(
                account_id=line.account_id,
                debit=line.credit,
                credit=line.debit,
                description=f"عكس: {line.description or ''}",
            ))

        from rawafed_bot.database.models.transaction import TransactionType
        reversal_tx = Transaction(
            transaction_type=TransactionType.REVERSAL.value,
            amount=sum(line.debit for line in original_lines),
            currency_id=original.currency_id,
            member_id=created_by,
            description=f"إلغاء القيد #{original.entry_number}: {reason}",
            status="active",
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        db.add(reversal_tx)
        db.flush()

        if original.transaction_id:
            original_tx = db.query(Transaction).filter_by(id=original.transaction_id).first()
            if original_tx:
                original_tx.status = "reversed"
                original_tx.reversed_transaction_id = reversal_tx.id
                db.add(original_tx)

        description = f"عكس القيد #{original.entry_number}: {reason}"
        entry = AccountingEngine.create_journal_entry(
            db=db,
            currency_id=original.currency_id,
            description=description,
            created_by=created_by,
            lines=reversal_lines,
            transaction_id=reversal_tx.id,
            idempotency_key=idempotency_key,
            reference_type="reversal",
            reference_id=original.id,
        )

        audit = AuditLog(
            action="reverse",
            entity_type="journal_entry",
            entity_id=original.id,
            member_id=created_by,
            old_values=f"entry_number={original.entry_number}",
            new_values=f"reversal_entry_id={entry.id}, reason={reason}",
        )
        db.add(audit)

        return entry
