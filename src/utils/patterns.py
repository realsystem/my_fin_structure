import re
from decimal import Decimal


def parse_amount(text: str) -> Decimal:
    """Parse a dollar amount string like '$1,234.56' or '-$50.00' to Decimal."""
    text = text.strip()
    negative = text.startswith("-") or text.startswith("(")
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return Decimal("0")
    amount = Decimal(cleaned)
    return -amount if negative else amount


def parse_date(text: str, year: int) -> tuple[int, int, int]:
    """Parse MM/DD format date, returning (year, month, day)."""
    match = re.match(r"(\d{1,2})/(\d{1,2})", text.strip())
    if not match:
        raise ValueError(f"Invalid date format: {text}")
    month, day = int(match.group(1)), int(match.group(2))
    return year, month, day


def clean_whitespace(text: str) -> str:
    """Normalize whitespace in text."""
    return " ".join(text.split())
