"""Contribution request & payment services."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from rawafed_bot.accounting.engine import AccountingEngine, JournalLineData
from rawafed_bot.database.models.contribution import (
    ContributionObligation,
    ContributionRequest,
    ContributionStatus,
)
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.transaction import Transaction, TransactionType
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.operation_service import OperationError
from rawafed_bot.utils.idempotency import generate_idempotency_key


class ContributionService:
    @staticmethod
    def create_request(
        db: Session,
        amount_per_member: int,
        currency_id: int,
        member_ids: List[int],
        created_by_telegram_id: int,
        description: str = None,
        due_date: datetime = None,
        idempotency_key: str = None,
    ) -> ContributionRequest:
        try:
            ceo = AuthService.require_contribution_creator(db, created_by_telegram_id)
            if amount_per_member <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            if not member_ids:
                raise OperationError("يجب اختيار عضو واحد على الأقل.")
            members = db.query(Member).filter(Member.id.in_(member_ids), Member.is_active == True).all()
            if len(members) != len(set(member_ids)):
                raise OperationError("بعض الأعضاء غير موجودين أو غير نشطين.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "contrib_req",
                    str(ceo.id),
                    str(currency_id),
                    str(amount_per_member),
                    ",".join(str(i) for i in sorted(set(member_ids))),
                    description or "",
                )
            existing = db.query(ContributionRequest).filter_by(
                created_by=ceo.id,
                amount=amount_per_member,
                currency_id=currency_id,
                description=description,
            ).order_by(ContributionRequest.id.desc()).first()
            # Soft idempotency via obligations not duplicated in same commit path
            req = ContributionRequest(
                amount=amount_per_member,
                currency_id=currency_id,
                description=description,
                due_date=due_date,
                status=ContributionStatus.PENDING.value,
                created_by=ceo.id,
            )
            db.add(req)
            db.flush()
            for member in members:
                db.add(ContributionObligation(
                    contribution_request_id=req.id,
                    member_id=member.id,
                    amount=amount_per_member,
                    paid_amount=0,
                    status=ContributionStatus.PENDING.value,
                ))
            db.commit()
            db.refresh(req)
            return req
        except Exception as exc:
            db.rollback()
            from rawafed_bot.services.operation_service import OperationService
            OperationService._reraise_integrity(exc)

    @staticmethod
    def list_requests(db: Session, status: str = None) -> List[ContributionRequest]:
        q = db.query(ContributionRequest).order_by(ContributionRequest.created_at.desc())
        if status:
            q = q.filter_by(status=status)
        return q.all()

    @staticmethod
    def get_request(db: Session, request_id: int) -> Optional[ContributionRequest]:
        return db.query(ContributionRequest).filter_by(id=request_id).first()

    @staticmethod
    def get_obligations(db: Session, request_id: int) -> List[ContributionObligation]:
        return db.query(ContributionObligation).filter_by(
            contribution_request_id=request_id
        ).all()

    @staticmethod
    def get_member_obligations(db: Session, member_id: int, open_only: bool = True):
        q = db.query(ContributionObligation).filter_by(member_id=member_id)
        if open_only:
            q = q.filter(ContributionObligation.status.in_([
                ContributionStatus.PENDING.value,
                ContributionStatus.PARTIAL.value,
                ContributionStatus.OVERDUE.value,
            ]))
        return q.all()

    @staticmethod
    def _refresh_statuses(db: Session, req: ContributionRequest, obligations: List[ContributionObligation]):
        now = datetime.utcnow()
        for ob in obligations:
            remaining = ob.amount - ob.paid_amount
            if remaining <= 0:
                ob.status = ContributionStatus.COMPLETED.value
            elif ob.paid_amount > 0:
                ob.status = ContributionStatus.PARTIAL.value
            elif req.due_date and req.due_date < now:
                ob.status = ContributionStatus.OVERDUE.value
            else:
                ob.status = ContributionStatus.PENDING.value
            db.add(ob)

        if all(o.status == ContributionStatus.COMPLETED.value for o in obligations):
            req.status = ContributionStatus.COMPLETED.value
        elif any(o.paid_amount > 0 for o in obligations):
            req.status = ContributionStatus.PARTIAL.value
        elif req.due_date and req.due_date < now:
            req.status = ContributionStatus.OVERDUE.value
        else:
            req.status = ContributionStatus.PENDING.value
        db.add(req)

    @staticmethod
    def pay_obligation(
        db: Session,
        obligation_id: int,
        amount: int,
        created_by: int,
        description: str = None,
        idempotency_key: str = None,
    ) -> Transaction:
        """Record a (partial) contribution payment into the cash box.

        Unpaid remainder never enters cash balances.
        """
        try:
            from rawafed_bot.services.operation_service import OperationService
            from rawafed_bot.services.permissions_catalog import PAY_CONTRIBUTION
            if amount <= 0:
                raise OperationError("المبلغ يجب أن يكون أكبر من صفر.")
            OperationService._require_actor_permission(db, created_by, PAY_CONTRIBUTION)
            obligation = db.query(ContributionObligation).filter_by(id=obligation_id).first()
            if not obligation:
                raise OperationError("الالتزام غير موجود.")
            remaining = obligation.amount - obligation.paid_amount
            if amount > remaining:
                raise OperationError(f"المبلغ أكبر من المتبقي ({remaining}).")
            req = db.query(ContributionRequest).filter_by(id=obligation.contribution_request_id).first()
            if not req:
                raise OperationError("طلب المساهمة غير موجود.")
            member_id = obligation.member_id
            currency_id = req.currency_id
            cash_box = AccountingEngine.get_account(db, "cash_box", currency_id)
            member_equity = AccountingEngine.get_account(db, "member_equity", currency_id, member_id)
            if not cash_box or not member_equity:
                raise OperationError("الحسابات المحاسبية غير موجودة لهذه العملة.")
            if not idempotency_key:
                idempotency_key = generate_idempotency_key(
                    "contrib_pay", str(obligation_id), str(amount), str(created_by)
                )
            OperationService._reject_duplicate_key(db, idempotency_key)
            desc = description or f"دفع مساهمة #{req.id}"
            # Reuse DEPOSIT type — money actually enters the box.
            tx = Transaction(
                transaction_type=TransactionType.DEPOSIT.value,
                amount=amount,
                currency_id=currency_id,
                member_id=member_id,
                description=desc,
                contribution_request_id=req.id,
                created_by=created_by,
                idempotency_key=idempotency_key,
            )
            db.add(tx)
            db.flush()
            obligation.paid_amount += amount
            lines = [
                JournalLineData(cash_box.id, debit=amount, credit=0, description="دفع مساهمة"),
                JournalLineData(member_equity.id, debit=0, credit=amount, description="مساهمة عضو"),
            ]
            AccountingEngine.create_journal_entry(
                db=db, currency_id=currency_id, description=desc,
                created_by=created_by, lines=lines, transaction_id=tx.id,
                idempotency_key=idempotency_key,
            )
            obligations = ContributionService.get_obligations(db, req.id)
            ContributionService._refresh_statuses(db, req, obligations)
            db.commit()
            db.refresh(tx)
            return tx
        except Exception as exc:
            db.rollback()
            from rawafed_bot.services.operation_service import OperationService
            OperationService._reraise_integrity(exc)

    @staticmethod
    def mark_overdue(db: Session) -> int:
        """Update overdue statuses. Returns number of obligations marked."""
        now = datetime.utcnow()
        count = 0
        requests = db.query(ContributionRequest).filter(
            ContributionRequest.status.in_([
                ContributionStatus.PENDING.value,
                ContributionStatus.PARTIAL.value,
            ])
        ).all()
        for req in requests:
            obligations = ContributionService.get_obligations(db, req.id)
            before = [(o.id, o.status) for o in obligations]
            ContributionService._refresh_statuses(db, req, obligations)
            after = [(o.id, o.status) for o in obligations]
            if before != after:
                count += sum(1 for b, a in zip(before, after) if b != a and a[1] == ContributionStatus.OVERDUE.value)
        db.commit()
        return count
