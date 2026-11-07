"""Runtime identity for RAWAFED BOT — tied to the active menu/build."""
from __future__ import annotations

import hashlib
import os

# Semantic app version
APP_VERSION = "2.1.0"

# Menu contract — bump whenever main reply-keyboard labels/layout change
MENU_VERSION = "menu-v4-no-advances-20261107"

# Fingerprint of the menu contract so logs prove which UI is running
_MENU_FINGERPRINT = hashlib.sha256(MENU_VERSION.encode("utf-8")).hexdigest()[:10]
CODE_BUILD_ID = f"{APP_VERSION}+{_MENU_FINGERPRINT}"

# Prefer hosting BUILD_ID env when set; otherwise code fingerprint
BUILD_ID = os.getenv("BUILD_ID", "").strip() or CODE_BUILD_ID

START_HANDLER = "rawafed_bot.bot.handlers.start.cmd_start"

WELCOME_REGISTERED = (
    "مرحباً بك في نظام روافد المالي.\n\n"
    "أنا محاسب روافد الذكي، مساعدكم في إدارة العمليات المالية "
    "ومتابعة الصندوق والمساهمات والالتزامات.\n\n"
    "يمكنك استخدام الأزرار التالية أو مخاطبتي مباشرة بكتابة: يا محاسب."
)

WELCOME_UNREGISTERED = (
    "مرحباً بك في نظام روافد المالي.\n\n"
    "لست مسجّلاً بعد كعضو نشط.\n"
    "سنكمل تسجيلك وملفك الشخصي هنا — دون منح صلاحيات مالية تلقائياً."
)
