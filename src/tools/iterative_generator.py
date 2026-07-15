"""Iterative AI-assisted provider generator that self-corrects using local LLM."""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.tools.ai_generator import AIProviderGenerator, OllamaClient
from src.utils.pdf import extract_text


@dataclass
class ExtractionState:
    """Tracks extraction progress across iterations."""
    bank_name: str = ""
    bank_id: str = ""
    detection_patterns: list[str] = field(default_factory=list)
    account_number_regex: str = ""
    account_number_found: str = ""
    statement_period_found: tuple[str, str] = ("", "")
    transaction_regex: str = ""
    transaction_columns: list[str] = field(default_factory=list)
    transactions_found: int = 0
    section_markers: dict[str, str] = field(default_factory=dict)
    summary_patterns: dict[str, str] = field(default_factory=dict)

    # Track what's working and what's not
    issues: list[str] = field(default_factory=list)
    successful_extractions: list[str] = field(default_factory=list)

    # Additional context to help LLM learn
    sample_transaction_lines: list[str] = field(default_factory=list)
    failed_regexes: list[str] = field(default_factory=list)
    iteration_count: int = 0
    date_formats_seen: list[str] = field(default_factory=list)
    amount_formats_seen: list[str] = field(default_factory=list)

    def to_config(self) -> dict:
        """Convert to provider config dict."""
        return {
            "bank_name": self.bank_name,
            "bank_id": self.bank_id,
            "detection_patterns": self.detection_patterns,
            "account_number_regex": self.account_number_regex,
            "statement_period_regex": "",  # Using robust fallback
            "statement_period_format": "numeric",
            "transaction_page": 1,
            "transaction_columns": self.transaction_columns or ["date", "description", "amount"],
            "transaction_regex": self.transaction_regex,
            "section_markers": self.section_markers,
            "summary_patterns": self.summary_patterns,
        }

    def save(self, path: Path) -> None:
        """Save state to JSON file."""
        data = {
            "bank_name": self.bank_name,
            "bank_id": self.bank_id,
            "detection_patterns": self.detection_patterns,
            "account_number_regex": self.account_number_regex,
            "account_number_found": self.account_number_found,
            "statement_period_found": list(self.statement_period_found),
            "transaction_regex": self.transaction_regex,
            "transaction_columns": self.transaction_columns,
            "transactions_found": self.transactions_found,
            "section_markers": self.section_markers,
            "summary_patterns": self.summary_patterns,
            "issues": self.issues,
            "successful_extractions": self.successful_extractions,
            "sample_transaction_lines": self.sample_transaction_lines,
            "failed_regexes": self.failed_regexes,
            "iteration_count": self.iteration_count,
            "date_formats_seen": self.date_formats_seen,
            "amount_formats_seen": self.amount_formats_seen,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "ExtractionState":
        """Load state from JSON file."""
        data = json.loads(path.read_text())
        state = cls()
        state.bank_name = data.get("bank_name", "")
        state.bank_id = data.get("bank_id", "")
        state.detection_patterns = data.get("detection_patterns", [])
        state.account_number_regex = data.get("account_number_regex", "")
        state.account_number_found = data.get("account_number_found", "")
        period = data.get("statement_period_found", ["", ""])
        state.statement_period_found = (period[0], period[1])
        state.transaction_regex = data.get("transaction_regex", "")
        state.transaction_columns = data.get("transaction_columns", [])
        state.transactions_found = data.get("transactions_found", 0)
        state.section_markers = data.get("section_markers", {})
        state.summary_patterns = data.get("summary_patterns", {})
        state.issues = data.get("issues", [])
        state.successful_extractions = data.get("successful_extractions", [])
        state.sample_transaction_lines = data.get("sample_transaction_lines", [])
        state.failed_regexes = data.get("failed_regexes", [])
        state.iteration_count = data.get("iteration_count", 0)
        state.date_formats_seen = data.get("date_formats_seen", [])
        state.amount_formats_seen = data.get("amount_formats_seen", [])
        return state


ITERATION_PROMPT = '''TASK: Fix the transaction parsing regex for this bank statement.

STEP 1: Look at these ACTUAL transaction lines from the PDF:
{sample_lines}

STEP 2: Analyze the format of each line. Break down the first line character by character:
- What comes first? (date like 06/15 or 06/15/26?)
- Is there a second date? (posting date)
- What is the description format?
- How is the amount shown? (with $ or without? negative with - or in parentheses?)

STEP 3: Write a regex that captures each part. The regex MUST:
- Start with ^ or match from line start
- Have capture groups () for each column
- End with $ to match full line
- Use \\d for digits, \\s for spaces, .+? for description

STEP 4: Test your regex mentally against each sample line. Does it match all of them?

STEP 5: Return JSON with your fix:
{{
  "transaction_regex": "your regex here",
  "transaction_columns": ["column names matching your capture groups"],
  "example_match": "show what groups would be captured from first sample line"
}}

CURRENT FAILING REGEX: {current_regex}
CURRENT COLUMNS: {current_columns}

The current regex does not match the sample lines. Create a NEW regex that matches them.

EXAMPLES OF WORKING PATTERNS:

Pattern for "06/15 STORE NAME 45.99":
{{"transaction_regex": "(\\d{{2}}/\\d{{2}})\\s+(.+?)\\s+(-?[\\d,.]+)$", "transaction_columns": ["date", "description", "amount"]}}

Pattern for "06/15 06/16 STORE NAME $45.99":
{{"transaction_regex": "(\\d{{2}}/\\d{{2}})\\s+(\\d{{2}}/\\d{{2}})\\s+(.+?)\\s+\\$(-?[\\d,.]+)$", "transaction_columns": ["date", "posting_date", "description", "amount"]}}

Pattern for "06/15 STORE NAME -$45.99" (negative with dollar):
{{"transaction_regex": "(\\d{{2}}/\\d{{2}})\\s+(.+?)\\s+(-?\\$[\\d,.]+)$", "transaction_columns": ["date", "description", "amount"]}}

Return ONLY the JSON object, no other text.'''


FIX_ACCOUNT = '''
Find the account number in the PDF text and create a regex:
"account_number_regex": "Account.*?(\\d{{4}}[\\s-]?\\d{{4}}[\\s-]?\\d{{4}}[\\s-]?\\d{{4}})"
'''

FIX_PERIOD = '''
Find the statement date range and note the format:
"statement_period_found": ["05/20/2026", "06/19/2026"]
'''

FIX_TRANSACTIONS = '''
Create a regex matching the sample transaction lines shown above.
'''


class IterativeGenerator:
    """Generate providers through iterative self-correction."""

    def __init__(
        self,
        model: str = "qwen2.5vl:3b",
        max_iterations: int = 15,
        log_fn: Callable[[str], None] | None = None,
        temp_mode: bool = False,
    ):
        self.temp_mode = temp_mode
        self.client = OllamaClient(model=model)
        self.base_generator = AIProviderGenerator(model=model)
        self.max_iterations = max_iterations
        self.log = log_fn or print

    def generate(
        self,
        pdf_path: Path,
        state_path: Path | None = None,
    ) -> tuple[bool, ExtractionState, Path | None]:
        """
        Iteratively generate a provider, learning from validation failures.

        Returns (success, final_state, provider_path)
        """
        if not self.client.is_available():
            raise RuntimeError(
                f"Ollama not available. Start with 'ollama serve' and ensure "
                f"model '{self.client.model}' is pulled."
            )

        # Load or create state
        if state_path and state_path.exists():
            state = ExtractionState.load(state_path)
            self.log(f"Resuming from saved state: {state.bank_name}")
        else:
            state = ExtractionState()
            state_path = state_path or Path(f".{pdf_path.stem}_state.json")

        text, pages = extract_text(pdf_path)
        sample_text = "\n\n---PAGE BREAK---\n\n".join(pages[:2])
        if len(sample_text) > 8000:
            sample_text = sample_text[:8000]

        # Initial analysis if no bank name yet
        if not state.bank_name:
            self.log("Running initial analysis...")
            try:
                config = self.base_generator.analyze_pdf(pdf_path)
                state.bank_name = config.get("bank_name", "Unknown")
                state.bank_id = config.get("bank_id", "unknown")
                state.detection_patterns = config.get("detection_patterns", [])
                state.account_number_regex = config.get("account_number_regex", "")
                state.transaction_regex = config.get("transaction_regex", "")
                state.transaction_columns = config.get("transaction_columns", [])
                state.section_markers = config.get("section_markers", {})
                state.summary_patterns = config.get("summary_patterns", {})
                self.log(f"Detected: {state.bank_name}")
            except Exception as e:
                self.log(f"Initial analysis failed: {e}")
                state.bank_name = "Unknown"
                state.bank_id = "unknown"

        # Get sample transaction lines once for the whole process
        sample_lines = self._extract_sample_lines(text, pages)
        state.sample_transaction_lines = sample_lines[:10]

        # Detect date and amount formats from samples
        state.date_formats_seen = self._detect_date_formats(sample_lines)
        state.amount_formats_seen = self._detect_amount_formats(sample_lines)

        # Iterative improvement loop
        for iteration in range(self.max_iterations):
            state.iteration_count = iteration + 1
            self.log(f"\n── Iteration {iteration + 1}/{self.max_iterations} ──")

            # Generate provider and validate
            # In temp mode, use _temp suffix to avoid overwriting existing providers
            if self.temp_mode:
                provider_path = Path(f"src/providers/{state.bank_id}_temp.py")
            else:
                provider_path = Path(f"src/providers/{state.bank_id}.py")
            config = state.to_config()

            code = self.base_generator.generate_provider_code(config, temp_mode=self.temp_mode)
            provider_path.write_text(code)

            success, message, stats = self.base_generator.validate_provider(
                provider_path, pdf_path
            )

            if success:
                self.log(f"✓ Validation passed: {message}")
                state.transactions_found = stats["transaction_count"]
                state.account_number_found = stats["account_number"]
                state.statement_period_found = tuple(stats["statement_period"])
                state.issues = []
                state.save(state_path)
                return True, state, provider_path

            # Parse validation failures
            state.issues = self._parse_issues(message)
            self.log(f"Issues: {', '.join(state.issues)}")

            # Ask LLM to fix specific issues - focus on transaction regex
            prompt = ITERATION_PROMPT.format(
                sample_lines="\n".join(f"  {i+1}. {line}" for i, line in enumerate(sample_lines[:8])),
                current_regex=state.transaction_regex or "(none)",
                current_columns=state.transaction_columns or ["date", "description", "amount"],
            )

            self.log("Asking LLM for fixes...")
            try:
                response = self.client.generate(prompt)
                fixes = self._parse_json_response(response)

                if fixes:
                    self._apply_fixes(state, fixes, sample_lines)
                    self.log(f"Attempted fixes: {list(fixes.keys())}")
                else:
                    self.log("No fixes received, trying heuristics...")

                # Always try heuristics if transactions still broken or unknown issues
                if "transactions" in state.issues or "unknown" in state.issues:
                    self._try_heuristic_fixes(state, text, pages, sample_lines)

            except Exception as e:
                self.log(f"Fix attempt failed: {e}")
                self._try_heuristic_fixes(state, text, pages, sample_lines)

            state.save(state_path)
            time.sleep(0.5)  # Small delay between iterations

        self.log(f"\n✗ Max iterations reached. Manual adjustment needed.")
        return False, state, provider_path

    def _detect_date_formats(self, sample_lines: list[str]) -> list[str]:
        """Detect date formats used in sample lines."""
        formats = []
        for line in sample_lines[:5]:
            if re.match(r"\d{2}/\d{2}/\d{2}", line):
                formats.append("MM/DD/YY")
            elif re.match(r"\d{2}/\d{2}/\d{4}", line):
                formats.append("MM/DD/YYYY")
            elif re.match(r"\d{2}/\d{2}\s", line):
                formats.append("MM/DD")
        return list(set(formats))

    def _detect_amount_formats(self, sample_lines: list[str]) -> list[str]:
        """Detect amount formats used in sample lines."""
        formats = []
        for line in sample_lines[:5]:
            if re.search(r"-\$[\d,.]+$", line):
                formats.append("-$AMOUNT")
            elif re.search(r"\$[\d,.]+$", line):
                formats.append("$AMOUNT")
            elif re.search(r"-[\d,.]+$", line):
                formats.append("-AMOUNT")
            elif re.search(r"[\d,.]+$", line):
                formats.append("AMOUNT")
        return list(set(formats))

    def _parse_issues(self, message: str) -> list[str]:
        """Parse validation error message into issue list."""
        issues = []
        if "Missing account number" in message:
            issues.append("account_number")
        if "Invalid statement period" in message:
            issues.append("statement_period")
        if "No transactions" in message:
            issues.append("transactions")
        if "empty description" in message:
            issues.append("transaction_description")
        if "zero amount" in message:
            issues.append("transaction_amount")
        return issues or ["unknown"]

    def _build_fix_instructions(self, issues: list[str]) -> str:
        """Build specific fix instructions based on issues."""
        instructions = []
        if "account_number" in issues:
            instructions.append(FIX_ACCOUNT)
        if "statement_period" in issues:
            instructions.append(FIX_PERIOD)
        if "transactions" in issues or "transaction_description" in issues or "transaction_amount" in issues:
            instructions.append(FIX_TRANSACTIONS)
        return "\n".join(instructions) or "Analyze the PDF and fix any parsing issues."

    def _extract_sample_lines(self, text: str, pages: list[str]) -> list[str]:
        """Extract lines that look like transactions."""
        samples = []
        # Look for lines starting with dates
        date_pattern = re.compile(r"^\d{1,2}/\d{1,2}")

        for page in pages[1:3] if len(pages) > 1 else pages:
            for line in page.split("\n"):
                line = line.strip()
                if date_pattern.match(line) and len(line) > 15:
                    # Skip header-like lines
                    if not any(h in line.lower() for h in ["date", "description", "amount", "balance", "summary"]):
                        samples.append(line)
                        if len(samples) >= 15:
                            break
        return samples

    def _parse_json_response(self, response: str) -> dict:
        """Extract JSON from LLM response."""
        json_match = re.search(r"\{[\s\S]*\}", response)
        if not json_match:
            return {}
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            return {}

    def _apply_fixes(
        self, state: ExtractionState, fixes: dict, sample_lines: list[str]
    ) -> None:
        """Apply fixes from LLM response to state, validating transaction regex."""
        if "account_number_regex" in fixes:
            state.account_number_regex = fixes["account_number_regex"]
        if "transaction_regex" in fixes:
            new_regex = fixes["transaction_regex"]
            try:
                compiled = re.compile(new_regex)
                # Test against sample lines - only accept if it matches at least one
                matches = sum(1 for line in sample_lines if compiled.match(line))
                if matches > 0:
                    state.transaction_regex = new_regex
                    self.log(f"  New regex matches {matches}/{len(sample_lines)} samples")
                else:
                    self.log(f"  Rejecting regex - matches 0 samples")
                    # Track failed regex to avoid repeating
                    if new_regex not in state.failed_regexes:
                        state.failed_regexes.append(new_regex)
            except re.error as e:
                self.log(f"  Rejecting invalid regex: {e}")
                if new_regex not in state.failed_regexes:
                    state.failed_regexes.append(new_regex)
        if "transaction_columns" in fixes and "transaction_regex" in fixes:
            # Only update columns if regex was accepted
            if state.transaction_regex == fixes.get("transaction_regex"):
                state.transaction_columns = fixes["transaction_columns"]
        if "section_markers" in fixes:
            state.section_markers = fixes["section_markers"]
        if "detection_patterns" in fixes:
            state.detection_patterns = fixes["detection_patterns"]
        if "summary_patterns" in fixes:
            state.summary_patterns = fixes["summary_patterns"]

    def _try_heuristic_fixes(
        self,
        state: ExtractionState,
        text: str,
        pages: list[str],
        sample_lines: list[str],
    ) -> None:
        """Apply heuristic fixes when LLM fails."""
        # For unknown issues, try all heuristics
        try_all = "unknown" in state.issues

        # Try to detect bank name and add detection patterns (only if not already set)
        if not state.bank_name or state.bank_name == "Unknown":
            bank_patterns = [
                # Order matters - more specific patterns first
                ("American Express", ["AMERICAN EXPRESS", "AMEX"]),
                ("Bank of America", ["BANK OF AMERICA", "BofA"]),
                ("Wells Fargo", ["WELLS FARGO"]),
                ("Capital One", ["CAPITAL ONE"]),
                ("Chase", ["CHASE", "JPMorgan Chase"]),
                ("Citi", ["CITI", "Citibank"]),
                ("Discover", ["DISCOVER"]),
            ]
            for bank_name, patterns in bank_patterns:
                for pattern in patterns:
                    if pattern.upper() in text.upper():
                        state.bank_name = bank_name
                        state.bank_id = bank_name.lower().replace(" ", "_")
                        state.detection_patterns = [pattern]
                        self.log(f"Heuristic: Detected bank: {bank_name}")
                        break
                if state.bank_name and state.bank_name != "Unknown":
                    break

        # Try to fix account number with common patterns
        if try_all or "account_number" in state.issues:
            for pattern in [
                r"Account.*?(\d{4}\s*\d{4}\s*\d{4}\s*\d{4})",
                r"Card.*?(\d{4}\s*\d{4}\s*\d{4}\s*\d{4})",
                r"ending in[:\s]*(\d{4})",
                r"(\d{16})",
            ]:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    state.account_number_regex = pattern
                    self.log(f"Heuristic: Found account pattern: {pattern[:50]}...")
                    break

        # Try to fix transactions with common patterns
        if (try_all or "transactions" in state.issues) and sample_lines:
            self.log(f"Heuristic: Analyzing {len(sample_lines)} sample lines...")
            self.log(f"Heuristic: Sample: {sample_lines[0][:60]}...")

            # Try common transaction formats (ordered by specificity)
            patterns = [
                # MM/DD/YY* DESCRIPTION -$AMOUNT (Amex format with asterisk)
                (r"(\d{2}/\d{2}/\d{2})\*?\s+(.+?)\s+(-?\$[\d,.]+)$",
                 ["date", "description", "amount"]),
                # MM/DD/YY DESCRIPTION -$AMOUNT or $AMOUNT
                (r"(\d{2}/\d{2}/\d{2,4})\s+(.+?)\s+(-?\$[\d,.]+)$",
                 ["date", "description", "amount"]),
                # MM/DD/YY DESCRIPTION AMOUNT (no dollar sign)
                (r"(\d{2}/\d{2}/\d{2,4})\s+(.+?)\s+(-?[\d,.]+)$",
                 ["date", "description", "amount"]),
                # MM/DD MM/DD DESCRIPTION AMOUNT (with optional - and $)
                (r"(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,.]+)$",
                 ["date", "posting_date", "description", "amount"]),
                # MM/DD DESCRIPTION -$AMOUNT or $AMOUNT
                (r"(\d{2}/\d{2})\s+(.+?)\s+(-?\$[\d,.]+)$",
                 ["date", "description", "amount"]),
                # MM/DD DESCRIPTION -AMOUNT or AMOUNT (Chase format)
                (r"(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,.]+)$",
                 ["date", "description", "amount"]),
            ]

            for pattern, columns in patterns:
                for line in sample_lines[:5]:
                    match = re.match(pattern, line)
                    if match:
                        state.transaction_regex = pattern
                        state.transaction_columns = columns
                        self.log(f"Heuristic: Matched pattern on: {line[:50]}...")
                        self.log(f"Heuristic: Groups: {match.groups()}")
                        return
            self.log("Heuristic: No pattern matched sample lines")
