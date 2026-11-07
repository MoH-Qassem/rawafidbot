"""Rawafed Bot — real entry point (not an Echo template)."""
from __future__ import annotations

import asyncio
import logging
import sys

from rawafed_bot.core.config import settings
from rawafed_bot.core.version import CODE_BUILD_ID, MENU_VERSION
from rawafed_bot.database.connection import get_db_context, init_db
from rawafed_bot.database.seeder import seed_all

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def setup():
    if not settings.is_valid:
        logger.error(
            "الإعدادات غير مكتملة. تحقق من BOT_TOKEN و CEO_TELEGRAM_ID "
            "دون كشف القيم السرية. الأعضاء يُسجَّلون عبر المجموعة."
        )
        sys.exit(1)

    logger.info(
        "setup build=%s code_build=%s menu=%s db_path=%s log_level=%s",
        settings.effective_build_id,
        CODE_BUILD_ID,
        MENU_VERSION,
        settings.db_path,
        settings.LOG_LEVEL,
    )
    existed = init_db()
    if existed:
        logger.info(
            "Existing database detected at %s — additive schema/seed only (no wipe).",
            settings.db_path,
        )
    else:
        logger.info("No prior database file — creating schema at %s", settings.db_path)

    with get_db_context() as db:
        seed_all(db)
    logger.info("Database ready (idempotent seed complete).")


async def main():
    setup()
    from rawafed_bot.bot.app import run_bot

    logger.info("Starting Rawafed Telegram bot (real app)…")
    await run_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (SIGINT/KeyboardInterrupt).")
        sys.exit(0)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)
