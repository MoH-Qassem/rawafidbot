"""Financial Operations Service for Rawafed Bot."""
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rawafed_bot.accounting.engine import AccountingEngine, JournalLineData, AccountingError
from rawafed_bot.database.models.transaction import Transaction, TransactionType
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.advance import Advance, AdvanceSettlement
from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.contribution import ContributionObligation, ContributionRequest
from rawafed_bot.utils.idempotency import generate_idempotency_key


class OperationError(Exception):
    """Raised when a business rule is violated."""
    pass


class OperationService:
    @staticmethod
    def _ensure_member(db: Session, member_id: int) -> Member:
        member = db.query(Member).filter_by(id=member_id).first()
        if not member:
            raise OperationError("العضو غير موجود.")
        return member

    @staticmethod
    def _require_actor_permission(db: Session, created_by: int, code: str) -> Member:
        """Enforce role permissions + block production ops before full registration."""
        from rawafed_bot.services.group_service import GroupService
        from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService
        from rawafed_bot.services.registration_service import RegistrationService

        actor = OperationService._ensure_member(db, created_by)
        if not actor.is_active:
            raise OperationError("حساب العضو غير نشط.")

        group = GroupService.get_primary(db)
        if group and group.is_setup_complete:
            status = RegistrationService.registration_status(db)
            if not status["complete"]:
                raise OperationError(
                    "⏳ لم يكتمل تسجيل أعضاء الشركة بعد. "
                    "أكمل تسجيل الأعضاء المعتمدين قبل العمليات الإنتاجية."
                )

        try:
            PermissionService.require(db, actor, code)
        except PermissionErrorDenied as exc:
            raise OperationError(str(exc)) from exc
        return actor

    @staticmethod
    def _reject_duplicate_key(db: Session, idempotency_key: str) -> None:
        if not idempotency_key:
            return
        existing = db.query(Transaction).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            raise OperationError("⚠️ هذه العملية تم تسجيلها مسبقاً. لا يمكن تكرارها.")
        existing_je = AccountingEngine.get_journal_entry_by_idempotency(db, idempotency_key)
        if existing_je:
            raise OperationError("⚠️ هذه العملية تم تسجيلها مسبقاً. لا يمكن تكرارها.")

    @staticmethod
    def _reraise_integrity(exc: Exception) -> None:
        """Map unique-constraint races to a clear duplicate error."""
        if isinstance(exc, IntegrityError):
            raise OperationError("⚠️ هذه العملية تم تسجيلها مسبقاً. لا يمكن تكرارها.") from exc
        raise exc

    @staticmethod
    def record_deposit(
        db: Session, amount: int, currency_id: int, member_id: int,
        description: str, created_by: int, idempotency_key: str = None,
    ) -> Transaction:
        try:
            from rawafed_bot.services.permissions_catalog import RECORD_DEPOSIT
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, RECORD_DEPOSIT)
            OperationService._ensure_member(db, member_id)
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            member_equity = AccountingEngine.get_account(db, "member_equity", currency_id, member_id)
            if not cash_box or not member_equity:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "deposit", str(member_id), str(currency_id), str(amount), description
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.DEPOSIT.value,
                amount=amount, currency_id=currency_id, member_id=member_id,
                description=description, created_by=created_by,
                idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            lines = [
                JournalLineData(cash_box.id, debit=amount, credit=0, description="إيداع نقدي"),
                JournalLineData(member_equity.id, debit=0, credit=amount, description="مساهمة عضو"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def record_expense_from_box(
        db: Session, amount: int, currency_id: int, category_id: int,
        member_id: int, description: str, created_by: int,
        idempotency_key: str = None,
    ) -> Transaction:
        try:
            from rawafed_bot.services.permissions_catalog import RECORD_EXPENSE
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, RECORD_EXPENSE)
            OperationService._ensure_member(db, member_id)
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            expense = AccountingEngine.get_account(db, "expense_summary", currency_id)
            if not cash_box or not expense:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "expense_box", str(member_id), str(currency_id), str(amount), description
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.EXPENSE.value,
                amount=amount, currency_id=currency_id, member_id=member_id,
                category_id=category_id, description=description,
                created_by=created_by, idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            lines = [
                JournalLineData(expense.id, debit=amount, credit=0, description="مصروف من الصندوق"),
                JournalLineData(cash_box.id, debit=0, credit=amount, description="دفع نقدي"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def record_personal_expense(
        db: Session, amount: int, currency_id: int, category_id: int,
        member_id: int, description: str, created_by: int,
        idempotency_key: str = None,
    ) -> Transaction:
        try:
            from rawafed_bot.services.permissions_catalog import RECORD_EXPENSE
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, RECORD_EXPENSE)
            OperationService._ensure_member(db, member_id)
            expense = AccountingEngine.get_account(db, "expense_summary", currency_id)
            member_due = AccountingEngine.get_account(db, "member_due", currency_id, member_id)
            if not expense or not member_due:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "personal_exp", str(member_id), str(currency_id), str(amount), description
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.PERSONAL_EXPENSE.value,
                amount=amount, currency_id=currency_id, member_id=member_id,
                category_id=category_id, description=description,
                created_by=created_by, idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            debt = MemberDebt(
                member_id=member_id, currency_id=currency_id,
                amount=amount, remaining=amount,
                description=description, transaction_id=tx.id,
                status="active",
            )
            db.add(debt)
            lines = [
                JournalLineData(expense.id, debit=amount, credit=0, description="مصروف دفعه العضو من ماله"),
                JournalLineData(member_due.id, debit=0, credit=amount, description="دين الشركة للعضو"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def record_debt_repayment(
        db: Session, amount: int, currency_id: int, member_id: int,
        description: str, created_by: int, debt_id: int,
        idempotency_key: str = None,
    ) -> Transaction:
        try:
            from rawafed_bot.services.permissions_catalog import VIEW_DEBTS
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, VIEW_DEBTS)
            OperationService._ensure_member(db, member_id)
            debt = db.query(MemberDebt).filter_by(id=debt_id, member_id=member_id).first()
            if not debt:
                raise OperationError("الدين غير موجود أو لا ينتمي لهذا العضو.")
            if debt.remaining < amount:
                raise OperationError(
                    f"المبلغ المطلوب ({amount}) أكبر من الدين المتبقي ({debt.remaining})."
                )
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            member_due = AccountingEngine.get_account(db, "member_due", currency_id, member_id)
            if not cash_box or not member_due:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "debt_repay", str(member_id), str(debt_id), str(amount)
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.DEBT_REPAYMENT.value,
                amount=amount, currency_id=currency_id, member_id=member_id,
                description=description, created_by=created_by,
                idempotency_key=idempotency_key,
                debt_id=debt.id,
            )
            db.add(tx)
            db.flush()
            debt.remaining -= amount
            if debt.remaining == 0:
                debt.status = "repaid"
            db.add(debt)
            lines = [
                JournalLineData(member_due.id, debit=amount, credit=0, description="تسديد مستحقات العضو"),
                JournalLineData(cash_box.id, debit=0, credit=amount, description="دفع نقدي من الصندوق"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def record_withdrawal(
        db: Session, amount: int, currency_id: int, member_id: int,
        description: str, created_by: int, idempotency_key: str = None,
    ) -> Transaction:
        """Final equity withdrawal from cash box (not an advance)."""
        try:
            from rawafed_bot.services.permissions_catalog import RECORD_WITHDRAWAL
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, RECORD_WITHDRAWAL)
            OperationService._ensure_member(db, member_id)
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            member_equity = AccountingEngine.get_account(db, "member_equity", currency_id, member_id)
            if not cash_box or not member_equity:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "withdrawal", str(member_id), str(currency_id), str(amount), description
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.WITHDRAWAL.value,
                amount=amount, currency_id=currency_id, member_id=member_id,
                description=description, created_by=created_by,
                idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            lines = [
                JournalLineData(member_equity.id, debit=amount, credit=0, description="سحب من حقوق العضو"),
                JournalLineData(cash_box.id, debit=0, credit=amount, description="صرف نقدي"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def record_withdrawal_as_advance(
        db: Session, amount: int, currency_id: int, member_id: int,
        description: str, purpose: str, created_by: int,
        idempotency_key: str = None,
    ) -> tuple:
        try:
            from rawafed_bot.services.permissions_catalog import MANAGE_ADVANCES
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, MANAGE_ADVANCES)
            OperationService._ensure_member(db, member_id)
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            advance_acc = AccountingEngine.get_account(db, "advance_pending", currency_id, member_id)
            if not cash_box or not advance_acc:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "advance", str(member_id), str(currency_id), str(amount), purpose or description
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.ADVANCE_ISSUED.value,
                amount=amount, currency_id=currency_id, member_id=member_id,
                description=description, created_by=created_by,
                idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            advance = Advance(
                member_id=member_id, currency_id=currency_id,
                amount=amount, purpose=purpose,
                status="open", created_by=created_by,
            )
            db.add(advance)
            db.flush()
            tx.advance_id = advance.id
            db.add(tx)
            lines = [
                JournalLineData(advance_acc.id, debit=amount, credit=0, description="تسليم عهدة"),
                JournalLineData(cash_box.id, debit=0, credit=amount, description="سحب من الصندوق"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx, advance
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def settle_advance(
        db: Session, advance_id: int, expense_amount: int,
        returned_amount: int, description: str, created_by: int,
        category_id: int = None, idempotency_key: str = None,
    ) -> tuple:
        try:
            from rawafed_bot.services.permissions_catalog import MANAGE_ADVANCES
            if expense_amount < 0 or returned_amount < 0:
                raise OperationError("المبالغ يجب أن تكون موجبة.")
            if expense_amount == 0 and returned_amount == 0:
                raise OperationError("يجب إدخال مبلغ مصروف أو مبلغ معاد على الأقل.")
            OperationService._require_actor_permission(db, created_by, MANAGE_ADVANCES)
            advance = db.query(Advance).filter_by(id=advance_id).first()
            if not advance:
                raise OperationError("العهدة غير موجودة.")
            if advance.status == "fully_settled":
                raise OperationError("العهدة مسواة بالكامل مسبقاً.")
            total = expense_amount + returned_amount
            if total > advance.amount:
                raise OperationError(
                    f"المجموع ({total}) لا يمكن أن يتجاوز قيمة العهدة ({advance.amount})."
                )
            additional_amount = advance.amount - total
            member_id = advance.member_id
            currency_id = advance.currency_id
            OperationService._ensure_member(db, member_id)
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            expense = AccountingEngine.get_account(db, "expense_summary", currency_id)
            advance_acc = AccountingEngine.get_account(db, "advance_pending", currency_id, member_id)
            member_due = AccountingEngine.get_account(db, "member_due", currency_id, member_id)
            if not cash_box or not expense or not advance_acc or not member_due:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "settle", str(advance_id), str(expense_amount), str(returned_amount)
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            tx = Transaction(
                transaction_type=TransactionType.ADVANCE_SETTLEMENT.value,
                amount=expense_amount or returned_amount, currency_id=currency_id,
                member_id=member_id, category_id=category_id,
                advance_id=advance.id, description=description,
                created_by=created_by, idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            settlement = AdvanceSettlement(
                advance_id=advance.id, expense_amount=expense_amount,
                returned_amount=returned_amount, additional_amount=additional_amount,
                description=description, created_by=created_by,
            )
            db.add(settlement)
            db.flush()
            # Accounting clears the full advance in one settlement.
            advance.status = "fully_settled"
            db.add(advance)
            lines = []
            if expense_amount > 0:
                lines.append(JournalLineData(
                    expense.id, debit=expense_amount, credit=0,
                    description="مصروف نهائي من العهدة",
                ))
            if returned_amount > 0:
                lines.append(JournalLineData(
                    cash_box.id, debit=returned_amount, credit=0,
                    description="إعادة المتبقي للصندوق",
                ))
            if additional_amount > 0:
                # Unreturned remainder stays as receivable-like (debit on member_due).
                lines.append(JournalLineData(
                    member_due.id, debit=additional_amount, credit=0,
                    description="متبقي عهدة غير مسوى",
                ))
            lines.append(JournalLineData(
                advance_acc.id, debit=0, credit=advance.amount,
                description="تصفية العهدة",
            ))
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=description,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            db.commit()
            return tx, settlement
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

    @staticmethod
    def reverse_transaction(
        db: Session, transaction_id: int, reason: str, created_by: int,
        idempotency_key: str = None,
    ) -> Transaction:
        """Reverse a financial transaction via reversing journal entry."""
        try:
            from rawafed_bot.services.permissions_catalog import REVERSE_OPERATIONS
            OperationService._require_actor_permission(db, created_by, REVERSE_OPERATIONS)
            tx = db.query(Transaction).filter_by(id=transaction_id).first()
            if not tx:
                raise OperationError("العملية غير موجودة.")
            if tx.status != "active":
                raise OperationError("لا يمكن إلغاء عملية غير نشطة.")
            if tx.transaction_type == TransactionType.REVERSAL.value:
                raise OperationError("لا يمكن إلغاء قيد عكسي مباشرة.")
            from rawafed_bot.database.models.journal import JournalEntry
            entry = db.query(JournalEntry).filter_by(transaction_id=tx.id).first()
            if not entry:
                raise OperationError("لا يوجد قيد محاسبي مرتبط بهذه العملية.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "reverse", str(transaction_id), reason
                )
            OperationService._reject_duplicate_key(db, idempotency_key)

            # Side-effect guards before posting the reversing journal
            if tx.transaction_type == TransactionType.PERSONAL_EXPENSE.value:
                debt = db.query(MemberDebt).filter_by(transaction_id=tx.id).first()
                if debt and debt.remaining != debt.amount:
                    raise OperationError(
                        "لا يمكن إلغاء مصروف شخصي بعد تسديد جزء من الدين المرتبط به."
                    )

            AccountingEngine.reverse_journal_entry(
                db=db, journal_entry_id=entry.id, reason=reason,
                created_by=created_by, idempotency_key=idempotency_key,
            )

            if tx.transaction_type == TransactionType.PERSONAL_EXPENSE.value:
                debt = db.query(MemberDebt).filter_by(transaction_id=tx.id).first()
                if debt and debt.status == "active":
                    debt.status = "cancelled"
                    debt.remaining = 0
                    db.add(debt)

            if tx.transaction_type == TransactionType.DEBT_REPAYMENT.value:
                debt = None
                if tx.debt_id:
                    debt = db.query(MemberDebt).filter_by(id=tx.debt_id).first()
                if debt:
                    debt.remaining = min(debt.amount, debt.remaining + tx.amount)
                    debt.status = "active"
                    db.add(debt)

            if tx.transaction_type == TransactionType.ADVANCE_ISSUED.value and tx.advance_id:
                advance = db.query(Advance).filter_by(id=tx.advance_id).first()
                if advance and advance.status == "open":
                    advance.status = "cancelled"
                    db.add(advance)

            if tx.transaction_type == TransactionType.ADVANCE_SETTLEMENT.value and tx.advance_id:
                advance = db.query(Advance).filter_by(id=tx.advance_id).first()
                if advance:
                    advance.status = "open"
                    db.add(advance)

            if tx.contribution_request_id:
                obligation = db.query(ContributionObligation).filter_by(
                    contribution_request_id=tx.contribution_request_id,
                    member_id=tx.member_id,
                ).first()
                if obligation:
                    obligation.paid_amount = max(0, obligation.paid_amount - tx.amount)
                    req = db.query(ContributionRequest).filter_by(
                        id=tx.contribution_request_id
                    ).first()
                    if req:
                        from rawafed_bot.services.contribution_service import ContributionService
                        obligations = ContributionService.get_obligations(db, req.id)
                        ContributionService._refresh_statuses(db, req, obligations)

            db.commit()
            db.refresh(tx)
            return tx
        except Exception as exc:
            db.rollback()
            OperationService._reraise_integrity(exc)

