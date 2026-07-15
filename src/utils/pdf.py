from pathlib import Path

import pdfplumber


def extract_text(pdf_path: Path) -> tuple[str, list[str]]:
    """Extract text from PDF, returning (full_text, list_of_page_texts)."""
    pages: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)

    full_text = "\n\n".join(pages)
    return full_text, pages


def extract_tables(pdf_path: Path) -> list[list[list[str | None]]]:
    """Extract all tables from PDF as list of tables, each table is list of rows."""
    all_tables: list[list[list[str | None]]] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            all_tables.extend(tables)

    return all_tables
