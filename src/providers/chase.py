"""Auto-generated provider for CHASE (AI-assisted)."""
import re
from datetime import date
from decimal import Decimal

from src.core.models import (
    AccountSummary,
    Statement,
    Transaction,
)
from src.providers.base import StatementProvider, register_provider


class ChaseProvider(StatementProvider):
    name = "CHASE"
    bank_id = "chase"

    def can_parse(self, text: str, pages: list[str]) -> float:
        score = 0.0
        if "chase".lower() in text.lower():
            score += 0.5
        if "freedom unlimited" in text.lower() or "sapphire" in text.lower():
            score += 0.4
        return min(score, 1.0)

    def parse(self, text: str, pages: list[str]) -> Statement:
        header_page = pages[0] if pages else text
        # Scan all pages for transactions
        all_pages_text = "\n".join(pages) if pages else text

        # Account number
        account_number = ""
        match = re.search(r"(\d{16})", header_page)
        if match:
            account_number = match.group(1)

        # Holder name
        holder_name = ""
        for line in header_page.split("\n"):
            line = line.strip()
            if re.match(r"^[A-Z][A-Z\s]+$", line) and len(line) > 5:
                holder_name = line
                break

        # Statement period
        statement_period = self._parse_statement_period(header_page)
        year = statement_period[1].year

        # Payment due date
        payment_due_date = None
        due_match = re.search(r"Payment Due Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})", all_pages_text, re.IGNORECASE)
        if due_match:
            payment_due_date = self._parse_date(due_match.group(1), year)

        # Minimum payment
        minimum_payment = None
        min_match = re.search(r"Minimum Payment[^\d]*(\$?[\d,.]+)", all_pages_text, re.IGNORECASE)
        if min_match:
            minimum_payment = self._parse_amount(min_match.group(1))

        # Summary
        def extract(pattern: str) -> Decimal:
            m = re.search(pattern, all_pages_text, re.IGNORECASE)
            if m:
                try:
                    return self._parse_amount(m.group(1))
                except IndexError:
                    return self._parse_amount(m.group(0))
            return Decimal("0")

        summary = AccountSummary(
            previous_balance=extract(r"Previous Balance[:\s]*\$?([\d,]+\.?\d*)"),
            payments_credits=extract(r"Payment[s]?,?\s*Credits?[:\s]*-?\$?([\d,]+\.?\d*)"),
            purchases_adjustments=extract(r"Purchases[:\s]*\+?\$?([\d,]+\.?\d*)"),
            fees=extract(r"Fees Charged[:\s]*\$?([\d,]+\.?\d*)"),
            interest=extract(r"Interest Charged[:\s]*\$?([\d,]+\.?\d*)"),
            new_balance=extract(r"New Balance[:\s]*\$?([\d,]+\.?\d*)"),
            credit_limit=extract(r"Credit (?:Access )?Line[:\s]*\$?([\d,]+\.?\d*)"),
            available_credit=extract(r"Available Credit[:\s]*\$?([\d,]+\.?\d*)"),
        )

        # Transactions
        transactions: list[Transaction] = []

        for line in all_pages_text.split("\n"):
            line = line.strip()

            match = re.match(r"(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,.]+)$", line)
            if match:
                trans_date = self._parse_date(match.group(1), year)
                description = match.group(2).strip()
                amount = self._parse_amount(match.group(3))
                post_date = trans_date

                # Determine category from amount sign and description
                if amount < 0 or 'PAYMENT' in description.upper():
                    category = "payment"
                else:
                    category = "purchase"

                transactions.append(Transaction(
                    transaction_date=trans_date,
                    posting_date=post_date,
                    description=description,
                    amount=amount,
                    category=category,
                    reference_number=None,
                ))

        return Statement(
            bank_name="CHASE",
            account_type="credit_card",
            account_number=account_number,
            holder_name=holder_name,
            statement_period=statement_period,
            closing_date=statement_period[1],
            payment_due_date=payment_due_date,
            minimum_payment=minimum_payment,
            summary=summary,
            transactions=transactions,
        )

    def _parse_statement_period(self, text: str) -> tuple[date, date]:
        # Try multiple common date range patterns
        patterns = [
            # MM/DD/YYYY - MM/DD/YYYY
            r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{4})",
            # MM/DD/YY - MM/DD/YY
            r"(\d{1,2}/\d{1,2}/\d{2})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{2})",
            # Month DD - Month DD, YYYY
            r"([A-Za-z]+\s+\d{1,2})\s*[-–to]+\s*([A-Za-z]+\s+\d{1,2}),?\s*(\d{4})",
            # Month DD, YYYY - Month DD, YYYY
            r"([A-Za-z]+\s+\d{1,2},?\s*\d{4})\s*[-–to]+\s*([A-Za-z]+\s+\d{1,2},?\s*\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    if match.lastindex == 3:
                        # Month DD - Month DD, YYYY format
                        year = int(match.group(3))
                        start = self._parse_month_day(match.group(1), year)
                        end = self._parse_month_day(match.group(2), year)
                    else:
                        start = self._parse_date(match.group(1), date.today().year)
                        end = self._parse_date(match.group(2), date.today().year)
                    if start < end:
                        return (start, end)
                except (ValueError, IndexError):
                    continue
        return (date.today(), date.today())

    def _parse_month_day(self, text: str, year: int) -> date:
        text = text.strip().replace(",", "")
        parts = text.split()
        if len(parts) >= 2:
            month = self._month_to_num(parts[0])
            day = int(parts[1])
            if len(parts) >= 3:
                year = int(parts[2])
            return date(year, month, day)
        raise ValueError(f"Cannot parse month/day: {text}")

    def _parse_amount(self, text: str) -> Decimal:
        text = text.strip()
        negative = text.startswith("-") or text.startswith("(")
        cleaned = re.sub(r"[^\d.]", "", text)
        # Handle edge cases like "." or empty
        if not cleaned or cleaned == ".":
            return Decimal("0")
        amount = Decimal(cleaned)
        return -amount if negative else amount

    def _parse_date(self, date_str: str, year: int) -> date:
        parts = re.split(r"[/\-]", date_str.strip())
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            return date(year, month, day)
        elif len(parts) == 3:
            month, day, yr = int(parts[0]), int(parts[1]), int(parts[2])
            if yr < 100:
                yr += 2000
            return date(yr, month, day)
        raise ValueError(f"Cannot parse date: {date_str}")

    def _month_to_num(self, month_name: str) -> int:
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        return months.get(month_name.lower(), 1)


register_provider(ChaseProvider())
