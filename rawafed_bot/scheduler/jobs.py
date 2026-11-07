"""Scheduled weekly/monthly reports and overdue contribution checks."""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from rawafed_bot.core.config import settings
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.reports.generator import ReportGenerator
from rawafed_bot.services.contribution_service import ContributionService

logger = logging.getLogger(__name__)


def _apscheduler_weekday(sunday_based: int) -> int:
    """Convert Sunday=0..Saturday=6 (project convention) to APScheduler Monday=0..Sunday=6."""
    return (int(sunday_based) - 1) % 7


def create_scheduler(bot=None) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    async def send_report(kind: str):
        try:
            with get_db_context() as db:
                date_from, date_to = ReportGenerator.period_bounds(kind)
                text = ReportGenerator.full_summary_text(db, date_from, date_to)
                path = ReportGenerator.export_period_excel(
                    db, date_from=date_from, date_to=date_to,
                    title=f"تقرير_{'أسبوعي' if kind == 'weekly' else 'شهري'}",
                )
            if bot is None:
                logger.info("Scheduled %s report generated: %s", kind, path)
                return
            from rawafed_bot.services.auth_service import AuthService
            with get_db_context() as db:
                members = AuthService.get_all_members(db)
                ids = [m.telegram_id for m in members]
            caption = f"📊 التقرير {'الأسبوعي' if kind == 'weekly' else 'الشهري'}\n\n{text[:3500]}"
            for tid in ids:
                try:
                    await bot.send_message(tid, caption)
                    from aiogram.types import FSInputFile
                    await bot.send_document(tid, FSInputFile(path), caption="ملف Excel")
                except Exception as exc:
                    logger.warning("Failed sending report to %s: %s", tid, exc)
        except Exception:
            logger.exception("Scheduled %s report failed", kind)

    async def check_overdue():
        try:
            with get_db_context() as db:
                n = ContributionService.mark_overdue(db)
            if n:
                logger.info("Marked %s contribution obligations overdue", n)
        except Exception:
            logger.exception("Overdue check failed")

    scheduler.add_job(
        send_report, CronTrigger(
            day_of_week=_apscheduler_weekday(settings.WEEKLY_REPORT_DAY),
            hour=settings.WEEKLY_REPORT_HOUR,
            minute=0,
            timezone=settings.TIMEZONE,
        ),
        args=["weekly"],
        id="weekly_report",
        replace_existing=True,
    )
    scheduler.add_job(
        send_report, CronTrigger(
            day=settings.MONTHLY_REPORT_DAY,
            hour=settings.MONTHLY_REPORT_HOUR,
            minute=0,
            timezone=settings.TIMEZONE,
        ),
        args=["monthly"],
        id="monthly_report",
        replace_existing=True,
    )
    scheduler.add_job(
        check_overdue, CronTrigger(hour=9, minute=0, timezone=settings.TIMEZONE),
        id="overdue_contributions",
        replace_existing=True,
    )
    return scheduler

