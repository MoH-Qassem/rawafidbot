"""aiogram application factory."""
from __future__ import annotations

import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from rawafed_bot.bot.handlers import setup_routers
from rawafed_bot.bot.middlewares.auth import AuthMiddleware
from rawafed_bot.core.config import settings
from rawafed_bot.core.version import APP_VERSION, BUILD_ID, MENU_VERSION, START_HANDLER

logger = logging.getLogger(__name__)

_scheduler_instance = None


def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    # Detach module-level routers so tests can rebuild a dispatcher safely
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
    for mod in (
        group_setup, group_ops, group_chat, start, guide, common, cashbox, expense,
        deposit, withdrawal, debts, members, history, reports, contributions,
        roles_admin, settings, group_noise,
    ):
        mod.router._parent_router = None
    setup_routers(dp)
    return dp


async def _log_runtime_identity(bot: Bot, dp: Dispatcher) -> None:
    names = [r.name for r in dp.sub_routers]
    me = await bot.get_me()
    logger.info("======== RAWAFED BOT RUNTIME ========")
    logger.info("APP_VERSION=%s", APP_VERSION)
    logger.info("BUILD_ID=%s", settings.effective_build_id)
    logger.info("CODE_BUILD_ID=%s", BUILD_ID)
    logger.info("MENU_VERSION=%s", MENU_VERSION)
    logger.info("START_HANDLER=%s", START_HANDLER)
    logger.info("routers_count=%s names=%s", len(names), ",".join(names))
    logger.info("db_path=%s", settings.db_path)
    logger.info("database_url=%s", settings.DATABASE_URL)
    logger.info("pid=%s", os.getpid())
    logger.info("telegram_bot_id=%s username=@%s", me.id, me.username)
    logger.info("=====================================")


async def run_bot() -> None:
    global _scheduler_instance
    if not settings.is_valid:
        raise RuntimeError(
            "الإعدادات غير مكتملة. تحقق من BOT_TOKEN و CEO_TELEGRAM_ID في ملف .env"
        )

    from rawafed_bot.bot.polling_lock import acquire_polling_lock, release_polling_lock

    acquire_polling_lock()

    bot = create_bot()
    dp = create_dispatcher()
    await _log_runtime_identity(bot, dp)

    scheduler = None
    try:
        from rawafed_bot.scheduler.jobs import create_scheduler

        if _scheduler_instance is not None and getattr(_scheduler_instance, "running", False):
            logger.warning("Scheduler already running in this process — skip duplicate")
            scheduler = _scheduler_instance
        else:
            scheduler = create_scheduler(bot)
            scheduler.start()
            _scheduler_instance = scheduler
            logger.info(
                "Scheduler started jobs=%s",
                [j.id for j in scheduler.get_jobs()],
            )
    except Exception:
        logger.exception("Scheduler not started (optional)")

    try:
        allowed = dp.resolve_used_update_types()
        logger.info(
            "Bot polling started build=%s menu=%s updates=%s",
            settings.effective_build_id,
            MENU_VERSION,
            ",".join(allowed),
        )
        # handle_signals=True: clean SIGINT/SIGTERM on Linux (FadeHost)
        # Sequential handling avoids SQLite write races under load.
        await dp.start_polling(
            bot,
            allowed_updates=allowed,
            handle_signals=True,
            close_bot_session=False,
            handle_as_tasks=False,
        )
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
            if _scheduler_instance is scheduler:
                _scheduler_instance = None
        await bot.session.close()
        release_polling_lock()
        logger.info("Shutdown complete build=%s", settings.effective_build_id)
