"""Prevent accidental duplicate polling processes for the same bot token."""
from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from rawafed_bot.core.config import settings

logger = logging.getLogger(__name__)
_held = False
_lock_path: Path | None = None


def _token_fingerprint() -> str:
    token = settings.BOT_TOKEN or "missing"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def lock_path() -> Path:
    """Store lock on the persistent data volume (Linux /data or local data/)."""
    return settings.data_dir / f"bot_polling_{_token_fingerprint()}.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, wintypes.DWORD(pid)
        )
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return int(kernel32.GetLastError()) == 5
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_lock(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return {"pid": int(raw), "token_fp": _token_fingerprint()}
        except ValueError:
            return {}


def acquire_polling_lock() -> None:
    global _held, _lock_path
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fp = _token_fingerprint()
    my_pid = os.getpid()

    if path.exists():
        data = _read_lock(path)
        old_pid = int(data.get("pid") or 0)
        old_fp = data.get("token_fp") or fp
        if old_pid and old_pid != my_pid and old_fp == fp:
            if _pid_alive(old_pid):
                raise RuntimeError(
                    f"Polling already running for this bot token "
                    f"(pid={old_pid}, lock={path}). "
                    "أوقف النسخة الأخرى يدوياً قبل التشغيل — لن يتم إيقافها تلقائياً."
                )
            logger.warning("Removing stale polling lock pid=%s file=%s", old_pid, path)

    payload = {
        "pid": my_pid,
        "token_fp": fp,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    _lock_path = path
    _held = True
    atexit.register(release_polling_lock)
    logger.info("Polling lock acquired pid=%s file=%s", my_pid, path)


def release_polling_lock() -> None:
    global _held, _lock_path
    if not _held:
        return
    path = _lock_path or lock_path()
    try:
        if path.exists():
            data = _read_lock(path)
            if int(data.get("pid") or 0) == os.getpid():
                path.unlink(missing_ok=True)
                logger.info("Polling lock released pid=%s", os.getpid())
            else:
                logger.warning(
                    "Skip deleting polling lock — owned by pid=%s (this=%s)",
                    data.get("pid"),
                    os.getpid(),
                )
    except Exception:
        logger.exception("Failed releasing polling lock")
    _held = False
    _lock_path = None
