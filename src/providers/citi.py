"""Provider for Citi credit card statements."""
import re
from datetime import date
from decimal import Decimal

from src.core.models import (
    AccountSummary,
    Statement,
    Transaction,
)
from src.providers.base import StatementProvider, register_provider


class CitiProvider(StatementProvider):
    name = "Citi"
    bank_id = "citi"

    def can_parse(self, text: str, pages: list[str]) -> float:
        score = 0.0
        if "citicards.com".lower() in text.lower():
            score += 0.45
        if "Citi Cards".lower() in text.lower():
            score += 0.45
        return min(score, 1.0)

    def parse(self, text: str, pages: list[str]) -> Statement:
        header_page = pages[0] if pages else text
        txn_page_idx = min(1, len(pages) - 1)
        txn_page = pages[txn_page_idx] if pages else text

        # Account number
        account_number = ""
        match = re.search(r"Account number ending in[:\s]*(\d{4})", header_page)
        if match:
            account_number = match.group(1)

        # Holder name (basic extraction)
        holder_name = ""
        for line in header_page.split("\n"):
            line = line.strip()
            if re.match(r"^[A-Z][A-Z\s]+$", line) and len(line) > 5:
                holder_name = line
                break

        # Statement period
        statement_period = (date.today(), date.today())
        match = re.search(r"(\d{1,2}/\d{2}/\d{2})-(\d{1,2}/\d{2}/\d{2})", header_page)
        if match:
            start = self._parse_date(match.group(1), date.today().year)
            end = self._parse_date(match.group(2), date.today().year)
            statement_period = (start, end)

        # Summary
        def extract(pattern: str) -> Decimal:
            m = re.search(pattern, header_page, re.IGNORECASE)
            if m:
                return self._parse_amount(m.group(1))
            return Decimal("0")

        summary = AccountSummary(
            previous_balance=extract(r"Previous balance \$([\d,.]+)"),
            payments_credits=extract(r"Payments -?\$([\d,.]+)"),
            purchases_adjustments=extract(r"Purchases \+?\$([\d,.]+)"),
            fees=Decimal("0"),
            interest=Decimal("0"),
            new_balance=extract(r"New balance \$([\d,.]+)"),
        )

        # Transactions
        transactions: list[Transaction] = []
        current_category = "purchase"
        year = statement_period[1].year
        pending_description = None

        for line in txn_page.split("\n"):
            line = line.strip()
            if "Payments, Credits" in line:
                current_category = "payment"
                continue
            if "Standard Purchases" in line:
                current_category = "purchase"
                continue

            # Payment line: "10/14 ONLINE PAYMENT, THANK YOU -$226.00"
            pay_match = re.match(r"(\d{2}/\d{2})\s+(.+?)\s+-\$(\d+\.\d{2})", line)
            if pay_match and current_category == "payment":
                trans_date = self._parse_date(pay_match.group(1), year)
                description = pay_match.group(2).strip()
                amount = -self._parse_amount(pay_match.group(3))
                transactions.append(Transaction(
                    transaction_date=trans_date,
                    posting_date=trans_date,
                    description=description,
                    amount=amount,
                    category="payment",
                    reference_number=None,
                ))
                continue

            # Purchase line: "09/21 09/21 COSTCO WHSE #0148 SAN JOSE CA $206.94"
            purch_match = re.match(r"(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+?)\s+\$(\d+\.\d{2})(?:\s|$)", line)
            if purch_match:
                trans_date = self._parse_date(purch_match.group(1), year)
                post_date = self._parse_date(purch_match.group(2), year)
                description = purch_match.group(3).strip()
                # Clean up descriptions that captured column headers
                description = re.sub(r"^(Sale|Post|Total|Date|Description|Amount|Costco Cash Rewards Balance:?)\s*", "", description)
                description = description.strip()
                if pending_description:
                    description = pending_description + " " + description
                    pending_description = None
                amount = self._parse_amount(purch_match.group(4))
                if description:
                    transactions.append(Transaction(
                        transaction_date=trans_date,
                        posting_date=post_date,
                        description=description,
                        amount=amount,
                        category="purchase",
                        reference_number=None,
                    ))
                continue

            # Multi-line transaction: description on one line, dates+amount on next
            # "BLACK BEAR DINER WILLOWS WILLOWS" then "10/11 10/11 $13.64"
            # Skip header lines
            if re.match(r"^[A-Z]", line) and not re.match(r"^\d", line) and "$" not in line:
                if len(line) > 10 and current_category == "purchase":
                    if "Date" not in line and "Description" not in line and "Amount" not in line:
                        pending_description = line
                    continue

            # Continuation line with just dates and amount
            cont_match = re.match(r"(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+\$(\d+\.\d{2})", line)
            if cont_match and pending_description:
                trans_date = self._parse_date(cont_match.group(1), year)
                post_date = self._parse_date(cont_match.group(2), year)
                amount = self._parse_amount(cont_match.group(3))
                transactions.append(Transaction(
                    transaction_date=trans_date,
                    posting_date=post_date,
                    description=pending_description,
                    amount=amount,
                    category="purchase",
                    reference_number=None,
                ))
                pending_description = None

        return Statement(
            bank_name="Citi",
            account_type="credit_card",
            account_number=account_number,
            holder_name=holder_name,
            statement_period=statement_period,
            closing_date=statement_period[1],
            payment_due_date=None,
            minimum_payment=None,
            summary=summary,
            transactions=transactions,
        )

    def _parse_amount(self, text: str) -> Decimal:
        text = text.strip()
        negative = text.startswith("-") or text.startswith("(")
        cleaned = re.sub(r"[^\d.]", "", text)
        if not cleaned:
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


register_provider(CitiProvider())
