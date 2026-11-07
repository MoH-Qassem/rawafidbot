"""Excel export with Arabic headers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rawafed_bot.core.config import BASE_DIR


def reports_dir() -> Path:
    path = BASE_DIR / "reports_output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_sheets(filename: str, sheets: Sequence[dict]) -> Path:
    """Export multiple sheets.

    sheets: list of {"title": str, "headers": list[str], "rows": list[list]}
    """
    wb = Workbook()
    # remove default sheet
    default = wb.active
    wb.remove(default)

    header_font = Font(bold=True, name="Arial")
    header_fill = PatternFill("solid", fgColor="D9EAD3")
    rtl = Alignment(horizontal="right", readingOrder=2)

    for spec in sheets:
        ws = wb.create_sheet(title=spec["title"][:31] or "Sheet")
        ws.sheet_view.rightToLeft = True
        headers = spec.get("headers") or []
        rows = spec.get("rows") or []
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = rtl
        for r_idx, row in enumerate(rows, start=2):
            for c_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=value)
                cell.alignment = rtl
        for col in range(1, len(headers) + 1):
            letter = get_column_letter(col)
            max_len = len(str(headers[col - 1])) if headers else 10
            for row in rows:
                if col - 1 < len(row) and row[col - 1] is not None:
                    max_len = max(max_len, len(str(row[col - 1])))
            ws.column_dimensions[letter].width = min(max(12, max_len + 2), 40)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = filename.replace(" ", "_")
    path = reports_dir() / f"{safe_name}_{stamp}.xlsx"
    wb.save(path)
    return path
