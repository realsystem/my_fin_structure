import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.utils.pdf import extract_text


@dataclass
class TransactionPattern:
    columns: list[str] = field(default_factory=lambda: ["date", "posting_date", "description", "amount"])
    line_regex: str = ""
    section_markers: dict[str, str] = field(default_factory=dict)
    has_posting_date: bool = True


@dataclass
class ProviderConfig:
    bank_name: str = ""
    bank_id: str = ""
    detection_patterns: list[str] = field(default_factory=list)
    account_number_regex: str = ""
    account_number_page: int = 0
    statement_period_regex: str = ""
    statement_period_format: str = "month_name"
    holder_name_regex: str = ""
    payment_due_date_regex: str = ""
    minimum_payment_regex: str = ""
    transaction_pattern: TransactionPattern = field(default_factory=TransactionPattern)
    transaction_page_hint: int = 2
    summary_patterns: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderConfig":
        tp = TransactionPattern(**d.pop("transaction_pattern", {}))
        return cls(transaction_pattern=tp, **d)


class PatternDetector:
    """Detect common patterns in PDF text."""

    ACCOUNT_PATTERNS = [
        (r"Account#?\s*(\d{4}\s*\d{4}\s*\d{4}\s*\d{4})", "16-digit card number"),
        (r"Account[:\s]*\.+(\d{4})", "Masked account (....1234)"),
        (r"Account[:\s#]*(\d{4,})", "Account number"),
        (r"(\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4})", "Card number with separators"),
    ]

    DATE_PERIOD_PATTERNS = [
        (r"(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s*(\d{4})", "month_name", "May 20 - June 19, 2026"),
        (r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–]\s*(\d{1,2}/\d{1,2}/\d{4})", "numeric", "01/01/2026 - 01/31/2026"),
        (r"(\w+)\s+(\d{1,2}),?\s*(\d{4})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s*(\d{4})", "month_name_full", "January 1, 2026 - January 31, 2026"),
    ]

    AMOUNT_PATTERN = r"-?\$?[\d,]+\.\d{2}"

    TRANSACTION_LINE_PATTERNS = [
        (r"(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+?)\s+(\d{4})\s+\d{4}\s+(-?[\d,]+\.?\d*)$",
         ["date", "posting_date", "description", "reference", "amount"],
         "MM/DD MM/DD DESC REF ACCT AMOUNT"),
        (r"(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})$",
         ["date", "posting_date", "description", "amount"],
         "MM/DD MM/DD DESC AMOUNT"),
        (r"(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})$",
         ["date", "description", "amount"],
         "MM/DD DESC AMOUNT"),
        (r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})$",
         ["date", "description", "amount"],
         "MM/DD/YYYY DESC AMOUNT"),
    ]

    def find_account_patterns(self, text: str) -> list[tuple[str, str, str]]:
        """Find account number candidates. Returns (match, pattern, description)."""
        results = []
        for pattern, desc in self.ACCOUNT_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches[:3]:
                results.append((m if isinstance(m, str) else m[0], pattern, desc))
        return results

    def find_date_period_patterns(self, text: str) -> list[tuple[str, str, str, str]]:
        """Find statement period candidates. Returns (match, pattern, format, example)."""
        results = []
        for pattern, fmt, example in self.DATE_PERIOD_PATTERNS:
            matches = re.findall(pattern, text)
            for m in matches[:2]:
                full_match = " ".join(m) if isinstance(m, tuple) else m
                results.append((full_match, pattern, fmt, example))
        return results

    def find_transaction_lines(self, text: str) -> list[tuple[str, list[str], str, list[str]]]:
        """Find transaction line patterns. Returns (pattern, columns, description, sample_matches)."""
        results = []
        lines = text.split("\n")

        for pattern, columns, desc in self.TRANSACTION_LINE_PATTERNS:
            matches = []
            for line in lines:
                m = re.match(pattern, line.strip())
                if m:
                    matches.append(line.strip())
                    if len(matches) >= 3:
                        break
            if matches:
                results.append((pattern, columns, desc, matches))

        return results

    def find_summary_labels(self, text: str) -> dict[str, list[str]]:
        """Find common summary field labels."""
        labels = {
            "previous_balance": [],
            "new_balance": [],
            "payments": [],
            "purchases": [],
            "fees": [],
            "interest": [],
            "credit_limit": [],
        }

        patterns = {
            "previous_balance": [r"Previous Balance", r"Beginning Balance", r"Last Statement Balance"],
            "new_balance": [r"New Balance", r"Statement Balance", r"Ending Balance", r"Total Balance"],
            "payments": [r"Payments", r"Credits", r"Payments and Credits"],
            "purchases": [r"Purchases", r"Charges", r"New Charges"],
            "fees": [r"Fees", r"Fee Charged"],
            "interest": [r"Interest", r"Interest Charged", r"Finance Charge"],
            "credit_limit": [r"Credit Line", r"Credit Limit", r"Available Credit"],
        }

        for field_name, field_patterns in patterns.items():
            for p in field_patterns:
                if re.search(p, text, re.IGNORECASE):
                    match = re.search(rf"({p})\s*:?\s*\$?([\d,]+\.?\d*)", text, re.IGNORECASE)
                    if match:
                        labels[field_name].append(match.group(0))

        return labels

    def find_section_markers(self, text: str) -> dict[str, str]:
        """Find transaction section markers."""
        markers = {}
        candidates = [
            ("payment", [r"Payments and Other Credits", r"Payments", r"Credits"]),
            ("purchase", [r"Purchases and Adjustments", r"Purchases", r"Transactions", r"Charges"]),
            ("interest", [r"Interest Charged", r"Finance Charges"]),
            ("fee", [r"Fees Charged", r"Fees"]),
        ]

        for category, patterns in candidates:
            for p in patterns:
                if re.search(rf"^{p}", text, re.IGNORECASE | re.MULTILINE):
                    markers[category] = p
                    break

        return markers


class ProviderGenerator:
    def __init__(self, pdf_path: Path):
        self.pdf_path = pdf_path
        self.text, self.pages = extract_text(pdf_path)
        self.detector = PatternDetector()
        self.config = ProviderConfig()

    def run_wizard(self, echo_fn, prompt_fn, confirm_fn) -> ProviderConfig:
        """Run interactive wizard. Takes click.echo, click.prompt, click.confirm as args."""
        echo_fn("\nProvider Generator")
        echo_fn("═" * 60)

        self._step_bank_info(echo_fn, prompt_fn)
        self._step_account_number(echo_fn, prompt_fn)
        self._step_statement_period(echo_fn, prompt_fn)
        self._step_transactions(echo_fn, prompt_fn, confirm_fn)
        self._step_summary(echo_fn, prompt_fn, confirm_fn)

        return self.config

    def _step_bank_info(self, echo_fn, prompt_fn):
        echo_fn("\n── Step 1: Bank Identification ──")
        preview = self.pages[0][:600] if self.pages else self.text[:600]
        echo_fn(f"\nFirst page preview:\n{preview}\n...")

        self.config.bank_name = prompt_fn("\nEnter bank name", default="")
        self.config.bank_id = prompt_fn(
            "Enter provider ID (lowercase, e.g. 'chase', 'wells_fargo')",
            default=self.config.bank_name.lower().replace(" ", "_").replace("-", "_")
        )

        echo_fn("\nEnter detection patterns (text that uniquely identifies this bank).")
        echo_fn("Enter one per line, empty line to finish:")
        patterns = []
        while True:
            p = prompt_fn("  Pattern", default="")
            if not p:
                break
            patterns.append(p)
        self.config.detection_patterns = patterns if patterns else [self.config.bank_name.lower()]

    def _step_account_number(self, echo_fn, prompt_fn):
        echo_fn("\n── Step 2: Account Number ──")

        candidates = self.detector.find_account_patterns(self.text)
        if candidates:
            echo_fn("\nFound candidates:")
            for i, (match, pattern, desc) in enumerate(candidates, 1):
                echo_fn(f"  [{i}] {match} ({desc})")
            echo_fn(f"  [{len(candidates) + 1}] Enter custom regex")

            choice = prompt_fn("Select", type=int, default=1)
            if 1 <= choice <= len(candidates):
                self.config.account_number_regex = candidates[choice - 1][1]
                echo_fn(f"Using regex: {self.config.account_number_regex}")
            else:
                self.config.account_number_regex = prompt_fn("Enter regex")
        else:
            echo_fn("No account patterns found automatically.")
            self.config.account_number_regex = prompt_fn("Enter account number regex")

    def _step_statement_period(self, echo_fn, prompt_fn):
        echo_fn("\n── Step 3: Statement Period ──")

        candidates = self.detector.find_date_period_patterns(self.text)
        if candidates:
            echo_fn("\nFound date patterns:")
            for i, (match, pattern, fmt, example) in enumerate(candidates, 1):
                echo_fn(f"  [{i}] {match}")
                echo_fn(f"       Format: {example}")
            echo_fn(f"  [{len(candidates) + 1}] Enter custom regex")

            choice = prompt_fn("Select", type=int, default=1)
            if 1 <= choice <= len(candidates):
                self.config.statement_period_regex = candidates[choice - 1][1]
                self.config.statement_period_format = candidates[choice - 1][2]
            else:
                self.config.statement_period_regex = prompt_fn("Enter regex")
                self.config.statement_period_format = prompt_fn("Format type", default="month_name")
        else:
            echo_fn("No date patterns found automatically.")
            self.config.statement_period_regex = prompt_fn("Enter statement period regex")

    def _step_transactions(self, echo_fn, prompt_fn, confirm_fn):
        echo_fn("\n── Step 4: Transactions ──")

        txn_page_idx = min(2, len(self.pages) - 1)
        echo_fn(f"\nShowing page {txn_page_idx + 1} (likely transactions):")
        txn_text = self.pages[txn_page_idx] if self.pages else self.text
        preview_lines = txn_text.split("\n")[:25]
        for line in preview_lines:
            echo_fn(f"  {line}")

        self.config.transaction_page_hint = prompt_fn(
            "\nWhich page typically has transactions? (0-indexed)",
            type=int,
            default=txn_page_idx
        )

        candidates = self.detector.find_transaction_lines(txn_text)
        if candidates:
            echo_fn("\nFound transaction patterns:")
            for i, (pattern, columns, desc, samples) in enumerate(candidates, 1):
                echo_fn(f"\n  [{i}] {desc}")
                echo_fn(f"       Columns: {', '.join(columns)}")
                echo_fn(f"       Samples:")
                for s in samples[:2]:
                    echo_fn(f"         {s}")
            echo_fn(f"\n  [{len(candidates) + 1}] Enter custom regex")

            choice = prompt_fn("Select", type=int, default=1)
            if 1 <= choice <= len(candidates):
                pattern, columns, _, _ = candidates[choice - 1]
                self.config.transaction_pattern.line_regex = pattern
                self.config.transaction_pattern.columns = columns
                self.config.transaction_pattern.has_posting_date = "posting_date" in columns
            else:
                self.config.transaction_pattern.line_regex = prompt_fn("Enter transaction line regex")
                cols = prompt_fn("Enter columns (comma-separated)", default="date,description,amount")
                self.config.transaction_pattern.columns = [c.strip() for c in cols.split(",")]
        else:
            echo_fn("No transaction patterns found automatically.")
            self.config.transaction_pattern.line_regex = prompt_fn("Enter transaction line regex")

        markers = self.detector.find_section_markers(txn_text)
        if markers:
            echo_fn(f"\nFound section markers: {markers}")
            if confirm_fn("Use these markers?", default=True):
                self.config.transaction_pattern.section_markers = markers

    def _step_summary(self, echo_fn, prompt_fn, confirm_fn):
        echo_fn("\n── Step 5: Account Summary ──")

        labels = self.detector.find_summary_labels(self.text)
        found_any = any(v for v in labels.values())

        if found_any:
            echo_fn("\nFound summary fields:")
            for field_name, matches in labels.items():
                if matches:
                    echo_fn(f"  {field_name}: {matches[0]}")

            if confirm_fn("Auto-generate summary patterns from these?", default=True):
                for field_name, matches in labels.items():
                    if matches:
                        label = matches[0].split()[0:3]
                        label_str = r"\s*".join(re.escape(w) for w in label)
                        self.config.summary_patterns[field_name] = rf"{label_str}\s*\$?([\d,]+\.?\d*)"

        if not self.config.summary_patterns:
            echo_fn("\nEnter summary field regexes (empty to skip):")
            for field in ["previous_balance", "new_balance", "payments", "purchases"]:
                pattern = prompt_fn(f"  {field}", default="")
                if pattern:
                    self.config.summary_patterns[field] = pattern

    def generate_code(self) -> str:
        """Generate provider Python code from config."""
        class_name = "".join(word.title() for word in self.config.bank_id.split("_"))

        detection_code = self._generate_detection_code()
        parse_code = self._generate_parse_code()

        return f'''"""Auto-generated provider for {self.config.bank_name}."""
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


class {class_name}Provider(StatementProvider):
    name = "{self.config.bank_name}"
    bank_id = "{self.config.bank_id}"

    def can_parse(self, text: str, pages: list[str]) -> float:
        score = 0.0
{detection_code}
        return min(score, 1.0)

    def parse(self, text: str, pages: list[str]) -> Statement:
        header_page = pages[0] if pages else text
        txn_page_idx = min({self.config.transaction_page_hint}, len(pages) - 1)
        txn_page = pages[txn_page_idx] if pages else text

{parse_code}

        return Statement(
            bank_name="{self.config.bank_name}",
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
        cleaned = re.sub(r"[^\\d.]", "", text)
        if not cleaned:
            return Decimal("0")
        amount = Decimal(cleaned)
        return -amount if negative else amount

    def _parse_date(self, date_str: str, year: int) -> date:
        parts = re.split(r"[/\\-]", date_str.strip())
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            return date(year, month, day)
        elif len(parts) == 3:
            month, day, yr = int(parts[0]), int(parts[1]), int(parts[2])
            if yr < 100:
                yr += 2000
            return date(yr, month, day)
        raise ValueError(f"Cannot parse date: {{date_str}}")

    def _month_to_num(self, month_name: str) -> int:
        months = {{
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }}
        return months.get(month_name.lower(), 1)


register_provider({class_name}Provider())
'''

    def _generate_detection_code(self) -> str:
        lines = []
        score_per = round(0.9 / max(len(self.config.detection_patterns), 1), 2)
        for pattern in self.config.detection_patterns:
            escaped = pattern.replace('"', '\\"')
            lines.append(f'        if "{escaped}".lower() in text.lower():')
            lines.append(f'            score += {score_per}')
        return "\n".join(lines) if lines else "        pass"

    def _generate_parse_code(self) -> str:
        lines = []

        lines.append(f'        # Account number')
        lines.append(f'        account_number = ""')
        lines.append(f'        match = re.search(r"{self.config.account_number_regex}", header_page)')
        lines.append(f'        if match:')
        lines.append(f'            account_number = match.group(1)')

        lines.append(f'')
        lines.append(f'        # Holder name (basic extraction)')
        lines.append(f'        holder_name = ""')
        lines.append(f'        for line in header_page.split("\\n"):')
        lines.append(f'            line = line.strip()')
        lines.append(f'            if re.match(r"^[A-Z][A-Z\\s]+$", line) and len(line) > 5:')
        lines.append(f'                holder_name = line')
        lines.append(f'                break')

        lines.append(f'')
        lines.append(f'        # Statement period')
        if self.config.statement_period_format == "month_name":
            lines.append(f'        statement_period = (date.today(), date.today())')
            lines.append(f'        match = re.search(r"{self.config.statement_period_regex}", header_page)')
            lines.append(f'        if match:')
            lines.append(f'            start_month = self._month_to_num(match.group(1))')
            lines.append(f'            start_day = int(match.group(2))')
            lines.append(f'            end_month = self._month_to_num(match.group(3))')
            lines.append(f'            end_day = int(match.group(4))')
            lines.append(f'            year = int(match.group(5))')
            lines.append(f'            start_year = year if start_month <= end_month else year - 1')
            lines.append(f'            statement_period = (date(start_year, start_month, start_day), date(year, end_month, end_day))')
        else:
            lines.append(f'        statement_period = (date.today(), date.today())')
            lines.append(f'        match = re.search(r"{self.config.statement_period_regex}", header_page)')
            lines.append(f'        if match:')
            lines.append(f'            start = self._parse_date(match.group(1), date.today().year)')
            lines.append(f'            end = self._parse_date(match.group(2), date.today().year)')
            lines.append(f'            statement_period = (start, end)')

        lines.append(f'')
        lines.append(f'        # Summary')
        lines.append(f'        def extract(pattern: str) -> Decimal:')
        lines.append(f'            m = re.search(pattern, header_page, re.IGNORECASE)')
        lines.append(f'            if m:')
        lines.append(f'                return self._parse_amount(m.group(1))')
        lines.append(f'            return Decimal("0")')
        lines.append(f'')

        summary_fields = {
            "previous_balance": 'Decimal("0")',
            "payments_credits": 'Decimal("0")',
            "purchases_adjustments": 'Decimal("0")',
            "fees": 'Decimal("0")',
            "interest": 'Decimal("0")',
            "new_balance": 'Decimal("0")',
        }

        field_mapping = {
            "previous_balance": "previous_balance",
            "payments": "payments_credits",
            "purchases": "purchases_adjustments",
            "fees": "fees",
            "interest": "interest",
            "new_balance": "new_balance",
        }

        for config_field, code_field in field_mapping.items():
            if config_field in self.config.summary_patterns:
                pattern = self.config.summary_patterns[config_field]
                summary_fields[code_field] = f'extract(r"{pattern}")'

        lines.append(f'        summary = AccountSummary(')
        lines.append(f'            previous_balance={summary_fields["previous_balance"]},')
        lines.append(f'            payments_credits={summary_fields["payments_credits"]},')
        lines.append(f'            purchases_adjustments={summary_fields["purchases_adjustments"]},')
        lines.append(f'            fees={summary_fields["fees"]},')
        lines.append(f'            interest={summary_fields["interest"]},')
        lines.append(f'            new_balance={summary_fields["new_balance"]},')
        lines.append(f'        )')

        lines.append(f'')
        lines.append(f'        # Transactions')
        lines.append(f'        transactions: list[Transaction] = []')
        lines.append(f'        current_category = "purchase"')
        lines.append(f'        year = statement_period[1].year')
        lines.append(f'')

        if self.config.transaction_pattern.section_markers:
            for cat, marker in self.config.transaction_pattern.section_markers.items():
                escaped = marker.replace('"', '\\"')
                lines.append(f'        # Section marker: {cat}')

        lines.append(f'        for line in txn_page.split("\\n"):')
        lines.append(f'            line = line.strip()')

        for cat, marker in self.config.transaction_pattern.section_markers.items():
            escaped = marker.replace('"', '\\"')
            lines.append(f'            if "{escaped}" in line and "TOTAL" not in line:')
            lines.append(f'                current_category = "{cat}"')
            lines.append(f'                continue')

        lines.append(f'            if line.startswith("TOTAL"):')
        lines.append(f'                continue')
        lines.append(f'')

        regex = self.config.transaction_pattern.line_regex
        cols = self.config.transaction_pattern.columns
        lines.append(f'            match = re.match(r"{regex}", line)')
        lines.append(f'            if match:')

        col_idx = 1
        for col in cols:
            if col == "date":
                lines.append(f'                trans_date = self._parse_date(match.group({col_idx}), year)')
            elif col == "posting_date":
                lines.append(f'                post_date = self._parse_date(match.group({col_idx}), year)')
            elif col == "description":
                lines.append(f'                description = match.group({col_idx}).strip()')
            elif col == "reference":
                lines.append(f'                ref_num = match.group({col_idx})')
            elif col == "amount":
                lines.append(f'                amount = self._parse_amount(match.group({col_idx}))')
            col_idx += 1

        if "posting_date" not in cols:
            lines.append(f'                post_date = trans_date')
        if "reference" not in cols:
            lines.append(f'                ref_num = None')

        lines.append(f'')
        lines.append(f'                if current_category == "payment":')
        lines.append(f'                    amount = -abs(amount)')
        lines.append(f'')
        lines.append(f'                transactions.append(Transaction(')
        lines.append(f'                    transaction_date=trans_date,')
        lines.append(f'                    posting_date=post_date,')
        lines.append(f'                    description=description,')
        lines.append(f'                    amount=amount,')
        lines.append(f'                    category=current_category,')
        lines.append(f'                    reference_number=ref_num,')
        lines.append(f'                ))')

        return "\n".join(lines)

    def save_provider(self, output_path: Path) -> None:
        """Save generated provider code to file."""
        code = self.generate_code()
        output_path.write_text(code)

    def save_config(self, output_path: Path) -> None:
        """Save configuration to JSON file."""
        output_path.write_text(json.dumps(self.config.to_dict(), indent=2))

    @classmethod
    def load_config(cls, config_path: Path) -> ProviderConfig:
        """Load configuration from JSON file."""
        data = json.loads(config_path.read_text())
        return ProviderConfig.from_dict(data)
