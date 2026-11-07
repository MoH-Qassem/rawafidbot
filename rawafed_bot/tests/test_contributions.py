"""Contribution request and payment tests."""
from datetime import datetime, timedelta

from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import Account, ContributionObligation, ContributionRequest
from rawafed_bot.services.contribution_service import ContributionService
from rawafed_bot.services.auth_service import AuthService


class TestContributions:
    def test_ceo_creates_request_no_cash_impact(self, db):
        seed_all(db)
        ceo = AuthService.get_member_by_telegram_id(db, 111111111)
        members = AuthService.get_all_members(db)
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        before = cash.balance
        req = ContributionService.create_request(
            db=db,
            amount_per_member=500,
            currency_id=currency_id,
            member_ids=[m.id for m in members[:2]],
            created_by_telegram_id=ceo.telegram_id,
            description="جولة تمويل",
            due_date=datetime.utcnow() + timedelta(days=7),
        )
        db.refresh(cash)
        assert cash.balance == before
        obligations = ContributionService.get_obligations(db, req.id)
        assert len(obligations) == 2
        assert all(o.paid_amount == 0 for o in obligations)

    def test_non_ceo_cannot_create(self, db):
        seed_all(db)
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        members = AuthService.get_all_members(db)
        non_ceo = next(m for m in members if not m.is_ceo)
        try:
            ContributionService.create_request(
                db=db, amount_per_member=100, currency_id=currency_id,
                member_ids=[non_ceo.id], created_by_telegram_id=non_ceo.telegram_id,
            )
            assert False, "should raise"
        except PermissionError:
            pass

    def test_partial_payment_updates_cash_and_remaining(self, db):
        seed_all(db)
        ceo = AuthService.get_member_by_telegram_id(db, 111111111)
        member = AuthService.get_member_by_telegram_id(db, 222222222)
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        req = ContributionService.create_request(
            db=db, amount_per_member=1000, currency_id=currency_id,
            member_ids=[member.id], created_by_telegram_id=ceo.telegram_id,
            description="مساهمة",
        )
        ob = ContributionService.get_obligations(db, req.id)[0]
        ContributionService.pay_obligation(
            db=db, obligation_id=ob.id, amount=400, created_by=member.id,
        )
        db.refresh(cash)
        db.refresh(ob)
        assert cash.balance == 400
        assert ob.paid_amount == 400
        assert ob.status == "partial"
        assert (ob.amount - ob.paid_amount) == 600
