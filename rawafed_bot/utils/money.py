"""Money helpers: parse/format amounts stored as integer minor units."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Union

from sqlalchemy.orm import Session

from rawafed_bot.database.models.currency import Currency

# Eastern Arabic + Persian digits → ASCII
_ARABIC_DIGIT_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


class MoneyError(Exception):
    pass


def normalize_amount_text(text: str) -> str:
    """Normalize user amount text: Arabic digits, spaces, thousand separators."""
    raw = (text or "").strip().translate(_ARABIC_DIGIT_MAP)
    raw = raw.replace(" ", "").replace("\u00a0", "").replace("٬", "").replace("،", "")
    # Keep one decimal separator: prefer last '.' or ','
    if raw.count(",") == 1 and raw.count(".") == 0:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    return raw


def get_currency(db: Session, currency_id: int) -> Currency:
    currency = db.query(Currency).filter_by(id=currency_id).first()
    if not currency:
        raise MoneyError("العملة غير موجودة.")
    return currency


def find_currency(db: Session, text: str) -> Optional[Currency]:
    """Resolve currency by code, Arabic/English name, symbol, or alias."""
    raw = (text or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    currencies = db.query(Currency).filter_by(is_active=True).all()
    for c in currencies:
        aliases = [a.strip() for a in (c.aliases or "").split(",") if a.strip()]
        exact = {
            c.code.upper(),
            (c.name_ar or "").strip(),
            (c.name_en or "").upper(),
            (c.symbol or "").strip(),
            *[a for a in aliases],
            *[a.upper() for a in aliases],
        }
        if raw in exact or upper in exact:
            return c
    for c in currencies:
        aliases = [a.strip() for a in (c.aliases or "").split(",") if a.strip()]
        pool = [c.code, c.name_ar, c.name_en, c.symbol, *aliases]
        if any(p and (raw in p or p in raw) for p in pool):
            return c
    return None


def to_minor_units(amount: Union[str, int, float, Decimal], decimal_places: int) -> int:
    """Convert a human amount to integer minor units."""
    try:
        if isinstance(amount, str):
            value = Decimal(normalize_amount_text(amount))
        else:
            value = Decimal(str(amount).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise MoneyError("المبلغ غير صالح.") from exc
    if value <= 0:
        raise MoneyError("المبلغ يجب أن يكون أكبر من صفر.")
    quant = Decimal(10) ** decimal_places
    minor = (value * quant).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if minor <= 0:
        raise MoneyError("المبلغ يجب أن يكون أكبر من صفر.")
    return int(minor)


def from_minor_units(amount: int, decimal_places: int) -> Decimal:
    quant = Decimal(10) ** decimal_places
    return (Decimal(amount) / quant).quantize(Decimal(10) ** -decimal_places)


def format_amount(amount: int, currency: Currency) -> str:
    value = from_minor_units(amount, currency.decimal_places)
    if currency.decimal_places == 0:
        formatted = f"{int(value):,}"
    else:
        formatted = f"{value:,.{currency.decimal_places}f}"
    return f"{formatted} {currency.code}"


def parse_user_amount(text: str, currency: Currency) -> int:
    cleaned = normalize_amount_text(text or "")
    if not cleaned:
        raise MoneyError("يرجى إدخال المبلغ.")
    return to_minor_units(cleaned, currency.decimal_places)
