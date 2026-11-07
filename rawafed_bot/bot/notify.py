"""Optional short group notifications after successful operations."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from sqlalchemy.orm import Session

from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.services.group_service import GroupService
from rawafed_bot.utils.money import format_amount

logger = logging.getLogger(__name__)

TYPE_AR = {
    "deposit": "إيداع",
    "expense": "مصروف",
    "withdrawal": "سحب",
    "personal_expense": "مصروف شخصي",
    "debt_repayment": "تسديد دين",
    "advance_issued": "عهدة",
    "advance_settlement": "تسوية عهدة",
}


async def notify_group_operation(bot: Bot, db: Session, tx: Transaction) -> None:
    group = GroupService.get_primary(db)
    if not group or not group.notify_operations:
        return
    level = getattr(group, "notify_detail_level", None) or "detailed"
    if level == "off":
        return
    member = db.query(Member).filter_by(id=tx.member_id).first()
    currency = db.query(Currency).filter_by(id=tx.currency_id).first()
    cash = db.query(Account).filter_by(
        account_type="cash_box", currency_id=tx.currency_id
    ).first()
    op = TYPE_AR.get(tx.transaction_type, tx.transaction_type)
    amt = format_amount(tx.amount, currency) if currency else str(tx.amount)
    bal = format_amount(cash.balance, currency) if cash and currency else "-"
    name = member.get_display_name() if member else str(tx.member_id)
    if level == "brief":
        text = f"✅ {op} #{tx.id} — {amt} — {name}"
    else:
        text = GroupService.format_operation_notice(
            tx_id=tx.id,
            member_name=name,
            amount_text=amt,
            op_type=op,
            description=(tx.description or "-")[:120],
            when=(tx.created_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M"),
            balance_text=bal,
        )
    try:
        await bot.send_message(group.chat_id, text)
    except Exception as exc:
        logger.warning("Group notify failed: %s", exc)
