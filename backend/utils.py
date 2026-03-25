"""Shared utilities for Birdie backend tools."""

import re


def _strip_fences(text: str) -> str:
    """Remove markdown code fences Claude occasionally adds despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text.strip()
