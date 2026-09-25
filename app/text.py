"""Helpers for showing user input inside Streamlit markdown."""

from __future__ import annotations

import re

MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def escape_markdown(text: str) -> str:
    """Backslash-escape markdown syntax so user input renders as plain text."""
    return MARKDOWN_SPECIAL.sub(r"\\\1", text)
