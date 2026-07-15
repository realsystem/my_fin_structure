import re
from datetime import date
from decimal import Decimal

from src.core.models import (
    AccountSummary,
    InterestRate,
    RewardsSummary,
    Statement,
    Transaction,
)
from src.providers.base import StatementProvider, register_provider


class BofACreditProvider(StatementProvider):
    name = "Bank of America Credit Card"
    bank_id = "bofa_credit"

    def can_parse(self, text: str, pages: list[str]) -> float:
        score = 0.0
        if "BANK OF AMERICA" in text.upper() or "bankofamerica.com" in text.lower():
            score += 0.3
        if "Visa Signature" in text or "Account#" in text:
            score += 0.3
        if re.search(r"Account#?\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}", text):
            score += 0.2
        if "Account Summary/Payment Information" in text:
            score += 0.2
        return min(score, 1.0)

    def parse(self, text: str, pages: list[str]) -> Statement:
        header_page = pages[0] if pages else text
        transactions_page = pages[2] if len(pages) > 2 else text
        rewards_page = pages[3] if len(pages) > 3 else ""

        account_number = self._parse_account_number(header_page)
        holder_name = self._parse_holder_name(header_page)
        statement_period = self._parse_statement_period(header_page)
        closing_date = statement_period[1]
        payment_due_date = self._parse_payment_due_date(header_page)
        minimum_payment = self._parse_minimum_payment(header_page)
        summary = self._parse_summary(header_page)
        transactions = self._parse_transactions(transactions_page, statement_period[1].year)
        interest_rates = self._parse_interest_rates(transactions_page)
        rewards = self._parse_rewards(rewards_page)

        return Statement(
            bank_name="Bank of America",
            account_type="credit_card",
            account_number=account_number,
            holder_name=holder_name,
            statement_period=statement_period,
            closing_date=closing_date,
            payment_due_date=payment_due_date,
            minimum_payment=minimum_payment,
            summary=summary,
            transactions=transactions,
            interest_rates=interest_rates,
            rewards=rewards,
        )

    def _parse_account_number(self, text: str) -> str:
        match = re.search(r"Account#?\s*(\d{4}\s*\d{4}\s*\d{4}\s*\d{4})", text)
        if match:
            return match.group(1).replace(" ", " ")
        return ""

    def _parse_holder_name(self, text: str) -> str:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if "WILMINGTON" in line.upper() or "P.O.BOX" in line.upper():
                continue
            if re.match(r"^[A-Z][A-Z\s]+$", line.strip()) and len(line.strip()) > 5:
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                if re.search(r"\d+.*WAY|ST|AVE|RD|DR|BLVD", next_line.upper()):
                    return line.strip()
        return ""

    def _parse_statement_period(self, text: str) -> tuple[date, date]:
        match = re.search(
            r"(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s*(\d{4})", text
        )
        if match:
            start_month = self._month_to_num(match.group(1))
            start_day = int(match.group(2))
            end_month = self._month_to_num(match.group(3))
            end_day = int(match.group(4))
            year = int(match.group(5))
            start_year = year if start_month <= end_month else year - 1
            return (
                date(start_year, start_month, start_day),
                date(year, end_month, end_day),
            )
        raise ValueError("Could not parse statement period")

    def _parse_payment_due_date(self, text: str) -> date | None:
        match = re.search(r"Payment Due Date\s*(\d{2})/(\d{2})/(\d{4})", text)
        if match:
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        return None

    def _parse_minimum_payment(self, text: str) -> Decimal | None:
        match = re.search(r"Total Minimum Payment Due\s*\$?([\d,]+\.?\d*)", text)
        if match:
            return Decimal(match.group(1).replace(",", ""))
        return None

    def _parse_summary(self, text: str) -> AccountSummary:
        def extract(pattern: str) -> Decimal:
            match = re.search(pattern, text)
            if match:
                val = match.group(1).replace(",", "").replace("$", "")
                return Decimal(val) if val else Decimal("0")
            return Decimal("0")

        previous_balance = extract(r"Previous Balance\s*\$?([\d,]+\.?\d*)")
        payments = extract(r"Payments and Other Credits\s*-?\$?([\d,]+\.?\d*)")
        purchases = extract(r"Purchases and Adjustments\s*\$?([\d,]+\.?\d*)")
        fees = extract(r"Fees Charged\s*\$?([\d,]+\.?\d*)")
        interest = extract(r"Interest Charged\s*\$?([\d,]+\.?\d*)")
        new_balance = extract(r"New Balance Total\s*\$?([\d,]+\.?\d*)")
        credit_limit = extract(r"Total Credit Line\s*\$?([\d,]+\.?\d*)")
        available = extract(r"Total Credit Available\s*\$?([\d,]+\.?\d*)")
        cash_line = extract(r"Cash Credit Line\s*\$?([\d,]+\.?\d*)")

        payments_match = re.search(r"Payments and Other Credits\s*(-?\$?[\d,]+\.?\d*)", text)
        if payments_match and "-" in payments_match.group(1):
            payments = -payments

        return AccountSummary(
            previous_balance=previous_balance,
            payments_credits=payments,
            purchases_adjustments=purchases,
            fees=fees,
            interest=interest,
            new_balance=new_balance,
            credit_limit=credit_limit if credit_limit else None,
            available_credit=available if available else None,
            cash_credit_line=cash_line if cash_line else None,
        )

    def _parse_transactions(self, text: str, year: int) -> list[Transaction]:
        transactions: list[Transaction] = []
        lines = text.split("\n")
        current_category = "purchase"

        for line in lines:
            line = line.strip()
            if "Payments and Other Credits" in line and "TOTAL" not in line:
                current_category = "payment"
                continue
            if "Purchases and Adjustments" in line and "TOTAL" not in line:
                current_category = "purchase"
                continue
            if "Interest Charged" in line and "TOTAL" not in line:
                current_category = "interest"
                continue
            if line.startswith("TOTAL"):
                continue

            match = re.match(
                r"(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+?)\s+(\d{4})\s+\d{4}\s+(-?[\d,]+\.?\d*)$",
                line,
            )
            if match:
                trans_date = self._parse_date(match.group(1), year)
                post_date = self._parse_date(match.group(2), year)
                description = match.group(3).strip()
                ref_num = match.group(4)
                amount_str = match.group(5).replace(",", "")
                amount = Decimal(amount_str)

                if current_category == "payment":
                    amount = -abs(amount)

                transactions.append(
                    Transaction(
                        transaction_date=trans_date,
                        posting_date=post_date,
                        description=description,
                        amount=amount,
                        category=current_category,
                        reference_number=ref_num,
                    )
                )

        return transactions

    def _parse_interest_rates(self, text: str) -> list[InterestRate]:
        rates: list[InterestRate] = []
        patterns = [
            (r"Purchases\s+([\d.]+)%V", "Purchases"),
            (r"Balance Transfers\s+([\d.]+)%V", "Balance Transfers"),
            (r"Direct Deposit and Check Cash\s*\n?Advances\s+([\d.]+)%V", "Cash Advances (Direct Deposit/Check)"),
            (r"Bank Cash Advances\s+([\d.]+)%V", "Bank Cash Advances"),
        ]
        for pattern, name in patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                rates.append(
                    InterestRate(
                        balance_type=name,
                        apr=Decimal(match.group(1)),
                        is_variable=True,
                    )
                )
        return rates

    def _parse_rewards(self, text: str) -> RewardsSummary | None:
        if "Reward Summary" not in text:
            return None

        def extract(pattern: str) -> Decimal:
            match = re.search(pattern, text)
            return Decimal(match.group(1)) if match else Decimal("0")

        return RewardsSummary(
            base_earned=extract(r"([\d.]+)\s+Base Cash Back Earned"),
            bonus_earned=extract(r"([\d.]+)\s+Category Bonus Earned"),
            relationship_bonus=extract(r"([\d.]+)\s+Relationship Bonus Earned"),
            total_available=extract(r"([\d.]+)\s+Total Cash Back Available"),
            reward_type="cash_back",
        )

    def _parse_date(self, date_str: str, year: int) -> date:
        month, day = map(int, date_str.split("/"))
        return date(year, month, day)

    def _month_to_num(self, month_name: str) -> int:
        months = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12,
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }
        return months.get(month_name, 1)


register_provider(BofACreditProvider())
