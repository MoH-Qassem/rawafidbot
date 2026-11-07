"""Build deployment/fadehost/ and a ZIP for FadeHost upload (no secrets, no venv)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "deployment" / "fadehost"
ZIP_PATH = ROOT / "deployment" / "rawafed-bot-fadehost.zip"

INCLUDE_ROOT_FILES = ("main.py", "requirements.txt")
INCLUDE_DIRS = ("rawafed_bot",)

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "venv",
    ".venv",
    "tests",
    "data",
    "backups",
    "reports_output",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".log", ".xlsx"}
EXCLUDE_NAMES = {".env", ".DS_Store", "Thumbs.db"}

PROD_REQUIREMENTS = """aiogram==3.17.0
SQLAlchemy==2.0.36
alembic==1.14.0
openpyxl==3.1.5
APScheduler==3.11.0
python-dotenv==1.0.1
aiohttp==3.11.11
pydantic==2.10.4
pydantic-settings==2.7.1
"""

GITIGNORE = """# FadeHost / local
.env
venv/
.venv/
__pycache__/
*.py[cod]
*.db
*.sqlite*
data/
backups/
reports_output/
*.log
.pytest_cache/
"""

ENV_EXAMPLE = """# انسخ القيم في لوحة FadeHost Environment Variables — لا ترفع ملف .env فيه أسرار.
BOT_TOKEN=
CEO_TELEGRAM_ID=
DB_PATH=/data/rawafed.db
TIMEZONE=Asia/Damascus
BUILD_ID=2.1.0+fadehost
LOG_LEVEL=INFO
# لا تفعّل على الإنتاج:
# ALLOW_ENV_MEMBER_BOOTSTRAP=0
# MEMBER_TELEGRAM_IDS=
"""


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIR_NAMES:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def copy_package_tree(src: Path, dest: Path) -> None:
    if src.is_dir():
        for item in src.rglob("*"):
            if should_skip(item):
                continue
            if item.is_dir():
                continue
            rel = item.relative_to(src)
            if any(p in EXCLUDE_DIR_NAMES for p in rel.parts):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    # main.py at package root
    shutil.copy2(ROOT / "main.py", OUT_DIR / "main.py")
    (OUT_DIR / "requirements.txt").write_text(PROD_REQUIREMENTS, encoding="utf-8")
    (OUT_DIR / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (OUT_DIR / ".env.example").write_text(ENV_EXAMPLE, encoding="utf-8")

    copy_package_tree(ROOT / "rawafed_bot", OUT_DIR / "rawafed_bot")

    # Remove tests from package if any slipped through
    tests_dir = OUT_DIR / "rawafed_bot" / "tests"
    if tests_dir.exists():
        shutil.rmtree(tests_dir)

    readme_src = ROOT / "deployment" / "README_DEPLOYMENT_AR.md"
    if readme_src.exists():
        shutil.copy2(readme_src, OUT_DIR / "README_DEPLOYMENT_AR.md")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in OUT_DIR.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(OUT_DIR).as_posix())

    print(f"Package dir: {OUT_DIR}")
    print(f"ZIP: {ZIP_PATH}")
    print(f"ZIP size bytes: {ZIP_PATH.stat().st_size}")


if __name__ == "__main__":
    main()
