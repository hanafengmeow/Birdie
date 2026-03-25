"""Layer 1 PDF parsers for plan_lookup.

_parse_with_pymupdf4llm and _parse_with_docling are lazy-imported so this
module loads for testing without heavy dependencies installed.
_slice_to_pages filters parser output to specific page numbers.
"""

import re
from typing import Optional


def _parse_with_pymupdf4llm(pdf_path: str) -> str:
    """Parser A — PyMuPDF4LLM: structured Markdown + per-page metadata.

    pymupdf4llm.to_markdown(page_chunks=True) returns list of chunk dicts:
      {"metadata": {"page": int, ...}, "text": str}
    Page markers allow the extractor to record correct page numbers per field.
    """
    try:
        import pymupdf4llm  # lazy: heavy dep, not always installed in test env
        chunks = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
        parts: list[str] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                meta = chunk.get("metadata", {})
                page = meta.get("page", "?")
                text = chunk.get("text", "")
            else:
                page, text = "?", str(chunk)
            parts.append(f"[PARSER_A PAGE {page}]\n{text}")
        return "\n\n".join(parts) or "[PARSER_A: no content extracted]"
    except Exception as exc:
        return f"[PARSER_A_FAILED: {exc}]"


def _parse_with_docling(pdf_path: str) -> str:
    """Parser B — Docling: full page layout analysis, tables, multi-column.

    Docling excels at SBC tables (the "Common Medical Events" grid is multi-column).
    Markdown export preserves reading order and table structure.
    """
    try:
        from docling.document_converter import DocumentConverter  # lazy
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        md = result.document.export_to_markdown()
        return f"[PARSER_B]\n{md}" if md else "[PARSER_B: no content extracted]"
    except Exception as exc:
        return f"[PARSER_B_FAILED: {exc}]"


def _slice_to_pages(raw_text: str, pages: set[int]) -> str:
    """Extract only the specified page sections from a raw parser output.

    Parser A uses markers like "[PARSER_A PAGE 3]". Parser B has no markers
    and always returns full text (we cannot split it without re-parsing).
    """
    if not pages:
        return raw_text

    page_pattern = re.compile(r"(\[PARSER_A PAGE \d+\])", re.IGNORECASE)
    sections = page_pattern.split(raw_text)

    if len(sections) <= 1:
        return raw_text  # no page markers found (Parser B) → return full text

    kept: list[str] = []
    current_page: Optional[int] = None
    for section in sections:
        match = re.match(r"\[PARSER_A PAGE (\d+)\]", section, re.IGNORECASE)
        if match:
            current_page = int(match.group(1))
            if current_page in pages:
                kept.append(section)
        elif current_page in pages:
            kept.append(section)

    return "\n".join(kept) if kept else raw_text
