"""Excel export of a skills table."""

from __future__ import annotations

import re
from io import BytesIO

import pandas as pd

MAX_NAME_CHARS = 60


def safe_filename(query: str) -> str:
    """File name for a query: letters, digits, dashes and underscores only."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", query.strip()).strip("_")[:MAX_NAME_CHARS]
    return f"{stem or 'skills'}_skills.xlsx"


def to_excel(df: pd.DataFrame) -> bytes:
    """One ``Skills`` sheet with columns sized to their content."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Skills")
        sheet = writer.sheets["Skills"]
        for idx, column in enumerate(df.columns):
            width = max([len(str(column)), *(len(str(v)) for v in df[column])]) + 2
            sheet.set_column(idx, idx, width)
    return buffer.getvalue()
