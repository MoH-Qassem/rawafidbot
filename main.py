"""Rawafed Bot — real entry point (not an Echo template)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from rawafed_bot.core.config import settings
from rawafed_bot.core.version import CODE_BUILD_ID, MENU_VERSION
from rawafed_bot.database.connection import get_db_context, init_db
from rawafed_bot.database.seeder import seed_all

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _maybe_wipe_database() -> None:
    """One-shot wipe when RESET_DB=1 (then clear the env flag in the host panel)."""
    flag = os.getenv("RESET_DB", "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        return
    db_path = Path(settings.db_path)
    for candidate in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    ):
        try:
            if candidate.exists():
                candidate.unlink()
                logger.warning("RESET_DB: deleted %s", candidate)
        except OSError as exc:
            logger.error("RESET_DB: failed to delete %s: %s", candidate, exc)
    logger.warning("RESET_DB: wipe complete — fresh schema/seed will follow.")


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
    _maybe_wipe_database()
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
