"""Telegram amount parsing + report/ledger consistency audit."""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rawafed_bot.accounting.ledger import (
    assert_all_entries_balanced,
    assert_stored_balances_match_ledger,
    cash_box_balance,
    expense_balance,
)
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.reports.generator import ReportGenerator
from rawafed_bot.services.operation_service import OperationService
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.services.report_service import ReportService
from rawafed_bot.tests.audit_helpers import cash, cat_id, currency_by_code, m, members
from rawafed_bot.utils.money import MoneyError, find_currency, format_amount, parse_user_amount


class TestTelegramMoneyParsing:
    def test_arabic_and_english_digits(self, db):
        seed_all(db)
        usd = currency_by_code(db, "USD")
        assert parse_user_amount("100.50", usd) == 10050
        assert parse_user_amount("١٠٠.٥٠", usd) == 10050
        assert parse_user_amount("1,400.01", usd) == 140001
        assert parse_user_amount("0.01", usd) == 1

    def test_currency_aliases(self, db):
        seed_all(db)
        assert find_currency(db, "دولار").code == "USD"
        assert find_currency(db, "USD").code == "USD"
        assert find_currency(db, "$").code == "USD"
        assert find_currency(db, "ليرة سورية").code == "SYP"
        assert find_currency(db, "TRY").code == "TRY"

    def test_invalid_inputs(self, db):
        seed_all(db)
        usd = currency_by_code(db, "USD")
        for bad in ["", "abc", "-10", "0", "٠", "--"]:
            with pytest.raises(MoneyError):
                parse_user_amount(bad, usd)

    def test_roundtrip_format(self, db):
        seed_all(db)
        usd = currency_by_code(db, "USD")
        minor = parse_user_amount("1234.56", usd)
        text = format_amount(minor, usd)
        assert "1,234.56" in text
        assert "USD" in text


class TestReportsMatchLedger:
    def test_reports_match_cash_and_expense(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(1000, "USD", db), cur.id, mem.id, "d", mem.id, "rp-d")
        OperationService.record_expense_from_box(
            db, m(250, "USD", db), cur.id, cat_id(db), mem.id, "e", mem.id, "rp-e"
        )
        OperationService.record_personal_expense(
            db, m(40, "USD", db), cur.id, cat_id(db), mem.id, "p", mem.id, "rp-p"
        )

        assert cash_box_balance(db, cur.id) == m(710, "USD", db)
        assert expense_balance(db, cur.id) == m(290, "USD", db)

        text = ReportService.cash_box_report(db)
        assert "710.00" in text or "710" in text

        rows = QueryService.cash_box_balances(db)
        usd_row = next(r for r in rows if r["currency"].code == "USD")
        assert usd_row["balance"] == cash(db, "USD").balance

        assert_all_entries_balanced(db)
        assert_stored_balances_match_ledger(db)

    def test_excel_matches_database(self, db, tmp_path, monkeypatch):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(333.33, "USD", db), cur.id, mem.id, "d", mem.id, "xl-d")
        OperationService.record_expense_from_box(
            db, m(33.33, "USD", db), cur.id, cat_id(db), mem.id, "e", mem.id, "xl-e"
        )

        import rawafed_bot.reports.excel_export as ee
        monkeypatch.setattr(ee, "BASE_DIR", tmp_path)

        path = ReportGenerator.export_period_excel(db, title="تدقيق")
        assert path.exists()
        wb = load_workbook(path)
        cash_sheet = wb["الصندوق"]
        # header + rows for 3 currencies
        usd_balance_cell = None
        for row in cash_sheet.iter_rows(min_row=2, values_only=True):
            if row[0] == "USD":
                usd_balance_cell = row[1]
                break
        assert usd_balance_cell is not None
        # Excel stores major units
        expected_major = cash(db, "USD").balance / (10 ** cur.decimal_places)
        assert abs(float(usd_balance_cell) - float(expected_major)) < 1e-9
