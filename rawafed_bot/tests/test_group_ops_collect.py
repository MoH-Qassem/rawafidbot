"""Regression: group_ops must not loop on «ما المبلغ؟» when currency is still missing."""
from __future__ import annotations

from rawafed_bot.bot.handlers.group_ops import _apply_field, _compute_missing, _order_missing
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.seeder import seed_all


def _base(op="withdrawal"):
    return {
        "op_type": op,
        "amount_text": None,
        "amount_minor": None,
        "currency_id": None,
        "currency_code": None,
        "description": "سحب",
        "category_id": None,
        "category_name": None,
    }


class TestApplyFieldNoAmountLoop:
    def test_amount_without_currency_advances_to_currency(self, db):
        seed_all(db)
        data = _base()
        missing, err = _apply_field(data, "amount", "150", db)
        assert err is None
        assert data["amount_text"] == "150"
        assert data["amount_minor"] is None  # needs currency first
        assert "amount" not in missing
        assert missing[0] == "currency"

    def test_currency_then_parses_prior_amount(self, db):
        seed_all(db)
        usd = db.query(Currency).filter_by(code="USD").one()
        data = _base()
        data["amount_text"] = "150"
        missing, err = _apply_field(data, "currency", usd.id, db)
        assert err is None
        assert data["amount_minor"] == 15000
        assert missing == []

    def test_amount_with_currency_word_completes(self, db):
        seed_all(db)
        data = _base()
        missing, err = _apply_field(data, "amount", "100 دولار", db)
        assert err is None
        assert data["currency_code"] == "USD"
        assert data["amount_minor"] == 10000
        assert missing == []

    def test_invalid_amount_with_currency_reasks_amount(self, db):
        seed_all(db)
        usd = db.query(Currency).filter_by(code="USD").one()
        data = _base()
        data["currency_id"] = usd.id
        data["currency_code"] = "USD"
        missing, err = _apply_field(data, "amount", "abc", db)
        assert err
        assert "amount" in missing
        assert data["amount_minor"] is None

    def test_compute_missing_orders_currency_before_amount(self):
        data = _base()
        data["description"] = None
        m = _compute_missing(data)
        assert m == _order_missing(["currency", "amount", "description"])
        assert m.index("currency") < m.index("amount")
