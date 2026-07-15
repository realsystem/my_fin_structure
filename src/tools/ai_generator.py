"""AI-assisted provider generator using Ollama."""

import importlib.util
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import requests

from src.utils.pdf import extract_text


class OllamaClient:
    """Simple Ollama client for provider generation."""

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
        timeout: int = 180,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        """Generate text using Ollama."""
        url = f"{self.base_url}/api/generate"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 4000,
                "temperature": 0.1,
            },
        }

        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json().get("response", "").strip()

    def is_available(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]
            return self.model.split(":")[0] in model_names
        except Exception:
            return False


ANALYSIS_PROMPT = '''You are analyzing a bank statement PDF. Your task is to find EXACT patterns in the text.

STEP 1: Read every line of this PDF text carefully:
"""
{pdf_text}
"""

STEP 2: Find and copy these EXACT values from the text above:
- Bank name (look for the bank's name in header)
- Account number (look for "Account", "Card", "Number", usually 4-16 digits)
- Statement dates (look for date ranges like "05/20/26 - 06/19/26" or "May 20 - June 19, 2026")
- Previous Balance amount (look for "Previous Balance" followed by a dollar amount)
- New Balance amount (look for "New Balance" followed by a dollar amount)
- Payment Due Date (look for "Payment Due" or "Due Date")
- Minimum Payment (look for "Minimum Payment")

STEP 3: Find 3-5 ACTUAL transaction lines. They usually look like:
- "06/15 STORE NAME CITY STATE 45.99"
- "06/15 06/16 STORE NAME 45.99"
- "Jun 15 STORE NAME $45.99"

Copy the exact transaction lines you find.

STEP 4: Based on what you found, create a regex pattern that matches those EXACT transaction lines.
For example, if you found "06/15 WALMART STORE 45.99", the regex would be:
(\\d{{2}}/\\d{{2}})\\s+(.+?)\\s+([\\d.]+)$

STEP 5: Return a JSON object:
{{
  "bank_name": "Bank Name You Found",
  "bank_id": "bank_name_lowercase",
  "detection_patterns": ["exact text from PDF that identifies this bank", "another unique text"],
  "account_number_regex": "regex with capture group for account number",
  "transaction_regex": "regex matching the EXACT transaction format you found",
  "transaction_columns": ["date", "description", "amount"],
  "section_markers": {{"payment": "exact payment section header", "purchase": "exact purchase section header"}},
  "example_transactions": ["copy 2-3 actual transaction lines here"]
}}

CRITICAL:
- Copy EXACT text from the PDF, do not make up patterns
- The transaction_regex MUST match the example_transactions you provide
- Use double backslashes in regex: \\\\d not \\d

Return ONLY the JSON object.'''


class AIProviderGenerator:
    """Generate bank statement providers using AI analysis."""

    def __init__(self, model: str = "qwen2.5vl:3b"):
        self.client = OllamaClient(model=model)

    def analyze_pdf(self, pdf_path: Path) -> dict:
        """Analyze PDF and return parsing configuration."""
        if not self.client.is_available():
            raise RuntimeError(
                f"Ollama not available. Start it with 'ollama serve' and ensure "
                f"model '{self.client.model}' is pulled."
            )

        text, pages = extract_text(pdf_path)

        # Send first 2 pages for analysis
        sample_text = "\n\n---PAGE BREAK---\n\n".join(pages[:2])
        if len(sample_text) > 8000:
            sample_text = sample_text[:8000]

        prompt = ANALYSIS_PROMPT.format(pdf_text=sample_text)
        response = self.client.generate(prompt)

        # Extract JSON from response
        json_match = re.search(r"\{[\s\S]*\}", response)
        if not json_match:
            raise ValueError(f"No JSON found in AI response:\n{response}")

        try:
            config = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from AI: {e}\n{response}")

        return config

    def generate_provider_code(self, config: dict, temp_mode: bool = False) -> str:
        """Generate Python provider code from config."""
        bank_id = config["bank_id"]
        if temp_mode:
            bank_id = f"{bank_id}_temp"
        class_name = "".join(word.title() for word in bank_id.split("_"))

        detection_code = self._generate_detection_code(config.get("detection_patterns", []))
        summary_code = self._generate_summary_code(config.get("summary_patterns", {}))
        transaction_code = self._generate_transaction_code(config)

        return f'''"""Auto-generated provider for {config["bank_name"]} (AI-assisted)."""
import re
from datetime import date
from decimal import Decimal

from src.core.models import (
    AccountSummary,
    Statement,
    Transaction,
)
from src.providers.base import StatementProvider, register_provider


class {class_name}Provider(StatementProvider):
    name = "{config["bank_name"]}"
    bank_id = "{bank_id}"

    def can_parse(self, text: str, pages: list[str]) -> float:
        score = 0.0
{detection_code}
        return min(score, 1.0)

    def parse(self, text: str, pages: list[str]) -> Statement:
        header_page = pages[0] if pages else text
        # Scan all pages for transactions
        all_pages_text = "\\n".join(pages) if pages else text

        # Account number
        account_number = ""
        acct_regex = r"{config.get("account_number_regex", "")}"
        if acct_regex:
            match = re.search(acct_regex, header_page)
            if match and match.lastindex:
                account_number = match.group(1)

        # Holder name
        holder_name = ""
        for line in header_page.split("\\n"):
            line = line.strip()
            if re.match(r"^[A-Z][A-Z\\s]+$", line) and len(line) > 5:
                holder_name = line
                break

        # Statement period
        statement_period = self._parse_statement_period(header_page)
        year = statement_period[1].year if statement_period else date.today().year

        # Payment due date
        payment_due_date = None
        due_match = re.search(r"Payment Due Date[:\\s]*(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})", all_pages_text, re.IGNORECASE)
        if due_match:
            payment_due_date = self._parse_date(due_match.group(1), year)

        # Minimum payment
        minimum_payment = None
        min_match = re.search(r"Minimum Payment[^\\d]*(\\$?[\\d,.]+)", all_pages_text, re.IGNORECASE)
        if min_match:
            minimum_payment = self._parse_amount(min_match.group(1))

        # Summary
{summary_code}

        # Transactions
{transaction_code}

        return Statement(
            bank_name="{config["bank_name"]}",
            account_type="credit_card",
            account_number=account_number,
            holder_name=holder_name,
            statement_period=statement_period,
            closing_date=statement_period[1] if statement_period else None,
            payment_due_date=payment_due_date,
            minimum_payment=minimum_payment,
            summary=summary,
            transactions=transactions,
        )

{self._generate_period_method(config)}

    def _parse_amount(self, text: str) -> Decimal:
        text = text.strip()
        negative = text.startswith("-") or text.startswith("(")
        cleaned = re.sub(r"[^\\d.]", "", text)
        # Handle edge cases like "." or empty
        if not cleaned or cleaned == ".":
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

    def _generate_detection_code(self, patterns: list[str]) -> str:
        if not patterns:
            return "        pass"
        lines = []
        score_per = round(0.9 / len(patterns), 2)
        for pattern in patterns:
            escaped = pattern.replace('"', '\\"')
            lines.append(f'        if "{escaped}".lower() in text.lower():')
            lines.append(f'            score += {score_per}')
        return "\n".join(lines)

    def _generate_summary_code(self, patterns: dict) -> str:
        # Always use robust default patterns - AI patterns are unreliable
        # These patterns work across most US bank statements
        lines = [
            "        def extract(pattern: str) -> Decimal:",
            "            m = re.search(pattern, all_pages_text, re.IGNORECASE)",
            "            if m:",
            "                try:",
            "                    return self._parse_amount(m.group(1))",
            "                except IndexError:",
            "                    return self._parse_amount(m.group(0))",
            "            return Decimal(\"0\")",
            "",
            "        summary = AccountSummary(",
            '            previous_balance=extract(r"Previous Balance[:\\s]*\\$?([\\d,]+\\.?\\d*)"),',
            '            payments_credits=extract(r"Payment[s]?,?\\s*Credits?[:\\s]*-?\\$?([\\d,]+\\.?\\d*)"),',
            '            purchases_adjustments=extract(r"Purchases[:\\s]*\\+?\\$?([\\d,]+\\.?\\d*)"),',
            '            fees=extract(r"Fees Charged[:\\s]*\\$?([\\d,]+\\.?\\d*)"),',
            '            interest=extract(r"Interest Charged[:\\s]*\\$?([\\d,]+\\.?\\d*)"),',
            '            new_balance=extract(r"New Balance[:\\s]*\\$?([\\d,]+\\.?\\d*)"),',
            '            credit_limit=extract(r"Credit (?:Access )?Line[:\\s]*\\$?([\\d,]+\\.?\\d*)"),',
            '            available_credit=extract(r"Available Credit[:\\s]*\\$?([\\d,]+\\.?\\d*)"),',
            "        )",
        ]
        return "\n".join(lines)

    def _generate_transaction_code(self, config: dict) -> str:
        columns = config.get("transaction_columns", ["date", "description", "amount"])
        regex = config.get("transaction_regex", "")
        markers = config.get("section_markers", {})

        # Validate and fix regex - count capture groups
        try:
            compiled = re.compile(regex)
            num_groups = compiled.groups
        except re.error:
            num_groups = 0

        # If regex has fewer groups than columns, use a fallback pattern
        if num_groups < len(columns):
            # Generate a basic pattern based on columns
            regex = self._generate_fallback_regex(columns)

        lines = [
            "        transactions: list[Transaction] = []",
            "",
            "        for line in all_pages_text.split(\"\\n\"):",
            "            line = line.strip()",
            "",
            f'            match = re.match(r"{regex}", line)',
            "            if match:",
        ]

        col_idx = 1
        for col in columns:
            if col == "date":
                lines.append(f"                trans_date = self._parse_date(match.group({col_idx}), year)")
            elif col == "posting_date":
                lines.append(f"                post_date = self._parse_date(match.group({col_idx}), year)")
            elif col == "description":
                lines.append(f"                description = match.group({col_idx}).strip()")
            elif col == "amount":
                lines.append(f"                amount = self._parse_amount(match.group({col_idx}))")
            col_idx += 1

        if "posting_date" not in columns:
            lines.append("                post_date = trans_date")

        lines.extend([
            "",
            "                # Skip zero-amount interest lines",
            "                if amount == Decimal('0') and 'INTEREST' in description.upper():",
            "                    continue",
            "",
            "                # Determine category from amount sign and description",
            "                if amount < 0 or 'PAYMENT' in description.upper():",
            '                    category = "payment"',
            "                elif 'INTEREST' in description.upper():",
            '                    category = "interest"',
            "                else:",
            '                    category = "purchase"',
            "",
            "                transactions.append(Transaction(",
            "                    transaction_date=trans_date,",
            "                    posting_date=post_date,",
            "                    description=description,",
            "                    amount=amount,",
            "                    category=category,",
            "                    reference_number=None,",
            "                ))",
        ])

        return "\n".join(lines)

    def _generate_fallback_regex(self, columns: list[str]) -> str:
        """Generate a basic transaction regex based on column names."""
        parts = []
        for col in columns:
            if col == "date":
                parts.append(r"(\d{2}/\d{2})")
            elif col == "posting_date":
                parts.append(r"(\d{2}/\d{2})")
            elif col == "description":
                parts.append(r"(.+?)")
            elif col == "amount":
                parts.append(r"(-?[\d,.]+)")
        return r"\s+".join(parts) + "$"

    def _generate_period_parsing(self, fmt: str) -> str:
        if fmt == "month_name":
            return '''        start_month = self._month_to_num(match.group(1))
        start_day = int(match.group(2))
        end_month = self._month_to_num(match.group(3))
        end_day = int(match.group(4))
        year = int(match.group(5))
        start_year = year if start_month <= end_month else year - 1
        return (date(start_year, start_month, start_day), date(year, end_month, end_day))'''
        else:
            return '''        start = self._parse_date(match.group(1), date.today().year)
        end = self._parse_date(match.group(2), date.today().year)
        return (start, end)'''

    def _generate_period_method(self, config: dict) -> str:
        """Generate robust statement period parsing with multiple fallback patterns."""
        ai_pattern = config.get("statement_period_regex", "")
        fmt = config.get("statement_period_format", "numeric")

        return '''    def _parse_statement_period(self, text: str) -> tuple[date, date] | None:
        # Try multiple common date range patterns
        patterns = [
            # MM/DD/YYYY - MM/DD/YYYY
            r"(\\d{1,2}/\\d{1,2}/\\d{4})\\s*[-–to]+\\s*(\\d{1,2}/\\d{1,2}/\\d{4})",
            # MM/DD/YY - MM/DD/YY
            r"(\\d{1,2}/\\d{1,2}/\\d{2})\\s*[-–to]+\\s*(\\d{1,2}/\\d{1,2}/\\d{2})",
            # Month DD - Month DD, YYYY
            r"([A-Za-z]+\\s+\\d{1,2})\\s*[-–to]+\\s*([A-Za-z]+\\s+\\d{1,2}),?\\s*(\\d{4})",
            # Month DD, YYYY - Month DD, YYYY
            r"([A-Za-z]+\\s+\\d{1,2},?\\s*\\d{4})\\s*[-–to]+\\s*([A-Za-z]+\\s+\\d{1,2},?\\s*\\d{4})",
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
        return None

    def _parse_month_day(self, text: str, year: int) -> date:
        text = text.strip().replace(",", "")
        parts = text.split()
        if len(parts) >= 2:
            month = self._month_to_num(parts[0])
            day = int(parts[1])
            if len(parts) >= 3:
                year = int(parts[2])
            return date(year, month, day)
        raise ValueError(f"Cannot parse month/day: {text}")'''

    def validate_provider(
        self, provider_path: Path, pdf_path: Path
    ) -> tuple[bool, str, dict | None]:
        """
        Validate a generated provider against its source PDF.

        Returns (success, message, stats) tuple.
        """
        # Load the provider module directly - don't use registry
        spec = importlib.util.spec_from_file_location("test_provider", provider_path)
        if not spec or not spec.loader:
            return False, f"Could not load provider from {provider_path}", None

        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            return False, f"Provider failed to load: {e}", None

        # Find the provider class directly from the loaded module
        provider = None
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and hasattr(obj, "can_parse")
                and hasattr(obj, "parse")
                and name.endswith("Provider")
                and name != "StatementProvider"
            ):
                provider = obj()
                break

        if provider is None:
            return False, "No provider class found in module", None

        # Extract PDF and check if provider can parse it
        text, pages = extract_text(pdf_path)
        score = provider.can_parse(text, pages)

        if score < 0.5:
            return False, f"Provider confidence too low: {score:.2f}", None

        # Parse the statement
        try:
            statement = provider.parse(text, pages)
        except Exception as e:
            return False, f"Provider failed to parse: {e}", None

        # Validate basic requirements - only transactions are required
        errors = []

        if not statement.transactions:
            errors.append("No transactions extracted")

        zero_amount_count = 0
        for i, txn in enumerate(statement.transactions):
            if not txn.description:
                errors.append(f"Transaction {i} has empty description")
            if txn.amount == Decimal("0"):
                zero_amount_count += 1

        # Fail only if ALL transactions have zero amount
        if zero_amount_count == len(statement.transactions):
            errors.append("All transactions have zero amount")

        if errors:
            return False, "; ".join(errors), None

        # Collect stats
        payments = sum(t.amount for t in statement.transactions if t.category == "payment")
        purchases = sum(t.amount for t in statement.transactions if t.category == "purchase")

        stats = {
            "account_number": statement.account_number,
            "statement_period": (
                statement.statement_period[0].isoformat(),
                statement.statement_period[1].isoformat(),
            ) if statement.statement_period else (None, None),
            "transaction_count": len(statement.transactions),
            "payments_total": str(payments),
            "purchases_total": str(purchases),
            "new_balance": str(statement.summary.new_balance) if statement.summary else "0",
        }

        return True, f"Validated: {len(statement.transactions)} transactions", stats

    def generate_tests(self, config: dict, stats: dict, pdf_filename: str) -> str:
        """Generate pytest test class for the new provider."""
        class_name = "".join(word.title() for word in config["bank_id"].split("_"))

        return f'''
class Test{class_name}Provider:
    """Tests for {config["bank_name"]} provider (auto-generated)."""

    @pytest.fixture
    def pdf_path(self):
        path = Path("{pdf_filename}")
        if not path.exists():
            pytest.skip("{config["bank_name"]} test PDF not found")
        return path

    @pytest.fixture
    def statement(self, pdf_path):
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "{config["bank_id"]}"
        return provider.parse(text, pages)

    def test_detection(self, pdf_path):
        """Provider should detect {config["bank_name"]} statement."""
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "{config["bank_id"]}"
        assert provider.can_parse(text, pages) >= 0.5

    def test_account_info(self, statement):
        """Should extract account information."""
        assert statement.bank_name == "{config["bank_name"]}"
        assert statement.account_type == "credit_card"
        assert statement.account_number == "{stats["account_number"]}"

    def test_statement_period(self, statement):
        """Should extract statement period dates."""
        start, end = statement.statement_period
        assert start < end

    def test_transactions_count(self, statement):
        """Should extract all transactions."""
        assert len(statement.transactions) == {stats["transaction_count"]}

    def test_transaction_totals(self, statement):
        """Transaction totals should match expected values."""
        payments = sum(t.amount for t in statement.transactions if t.category == "payment")
        purchases = sum(t.amount for t in statement.transactions if t.category == "purchase")

        assert payments == Decimal("{stats["payments_total"]}")
        assert purchases == Decimal("{stats["purchases_total"]}")
'''

    def add_tests_to_file(self, test_code: str, test_file: Path) -> None:
        """Append test class to existing test file."""
        if not test_file.exists():
            # Create new test file with imports
            content = '''"""Tests for bank statement providers."""
import pytest
from decimal import Decimal
from pathlib import Path

from src.providers.base import load_providers, registry
from src.utils.pdf import extract_text


@pytest.fixture(scope="module", autouse=True)
def setup_providers():
    """Load all providers before tests."""
    load_providers()

'''
            content += test_code
            test_file.write_text(content)
        else:
            # Append to existing file
            existing = test_file.read_text()
            test_file.write_text(existing + "\n" + test_code)

    def register_provider(self, bank_id: str, base_path: Path) -> bool:
        """Add provider import to base.py."""
        base_file = base_path / "providers" / "base.py"
        if not base_file.exists():
            return False

        content = base_file.read_text()
        import_line = f"    from src.providers import {bank_id}"

        # Check if already registered
        if import_line in content:
            return True

        # Find load_providers function and add import
        if "def load_providers()" in content:
            # Add import before the last line of the function
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.strip().startswith("def load_providers"):
                    # Find the end of the function (next line at same indent or less)
                    j = i + 1
                    while j < len(lines):
                        if lines[j].strip() and not lines[j].startswith("    "):
                            break
                        if lines[j].strip().startswith("from src.providers"):
                            # Insert after last import
                            pass
                        j += 1
                    # Insert before j
                    lines.insert(j, import_line)
                    break

            base_file.write_text("\n".join(lines))
            return True

        return False

    def run_tests(self, bank_id: str) -> tuple[bool, str]:
        """Run pytest for specific provider tests."""
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "tests/test_providers.py", "-v", "-k", bank_id,
                "--tb=short"
            ],
            capture_output=True,
            text=True,
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        return success, output
