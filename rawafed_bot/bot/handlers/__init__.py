"""Register all bot routers — start router owns /start (MENU_VERSION active UI)."""
from aiogram import Dispatcher

from rawafed_bot.bot.handlers import (
    cashbox,
    common,
    contributions,
    debts,
    deposit,
    expense,
    group_chat,
    group_noise,
    group_ops,
    group_setup,
    guide,
    history,
    members,
    reports,
    roles_admin,
    settings,
    start,
    withdrawal,
)


def setup_routers(dp: Dispatcher) -> None:
    # Group setup / intelligence / NL ops first
    dp.include_router(group_setup.router)
    dp.include_router(group_ops.router)
    dp.include_router(group_chat.router)
    # /start + menu taps BEFORE FSM collectors so buttons always win
    dp.include_router(start.router)
    dp.include_router(guide.router)
    dp.include_router(common.router)
    dp.include_router(cashbox.router)
    dp.include_router(members.router)
    dp.include_router(history.router)
    dp.include_router(reports.router)
    dp.include_router(contributions.router)
    dp.include_router(roles_admin.router)
    dp.include_router(settings.router)
    # Multi-step financial FSMs after menu routers
    dp.include_router(expense.router)
    dp.include_router(deposit.router)
    dp.include_router(withdrawal.router)
    dp.include_router(debts.router)
    # Last: quiet acknowledgement of non-targeted group chatter
    dp.include_router(group_noise.router)
