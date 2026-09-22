"""Detector for monetary amounts and balances."""

import re
from typing import Optional

from .base import Detector
from ..core.models import Detection, TextBlock


class AmountDetector(Detector):
    """Detects monetary amounts, balances, and financial values."""

    # Pattern for amounts: $1,234.56 or 1234.56 or (1,234.56)
    AMOUNT_PATTERN = re.compile(
        r"[\(\$]?[\s]*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?|\d+\.\d{2})[\s]*[\)]?"
    )

    # Pattern for labeled amounts: "Payment: $1000" or "New Balance: $5000"
    LABELED_AMOUNT_PATTERN = re.compile(
        r"(payment|new\s+balance|balance|amount|total|due|charged|credited|debit|credit)\s*:?\s*([\(\$]?[\s]*\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?|\d+\.\d{2})[\s]*[\)]?",
        re.IGNORECASE
    )

    # Patterns that look like amounts but should be preserved
    PRESERVE_PATTERNS = [
        r"^Page\s+\d+\s+of\s+\d+$",  # Page numbers
        r"^\d{1,2}/\d{1,2}/\d{4}$",  # Dates
        r"^#\d+$",  # Check numbers (start with #)
        r"^\d{4}$",  # Year alone
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)",  # Month names
    ]

    # Context words that indicate an amount field
    AMOUNT_CONTEXT = [
        "balance", "amount", "debit", "credit", "charge", "payment", "deposit",
        "withdrawal", "total", "subtotal", "interest", "fee", "available",
        "beginning", "ending", "transaction", "available funds", "minimum payment",
        "payment due", "cash advance", "purchase", "fee amount", "apy",
    ]

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect monetary amounts and account balances."""
        detections = []

        for block in text_blocks:
            text = self._normalize_text(block.text)

            # Skip empty or very short
            if len(text) < 2:
                continue

            # Check preservation patterns first
            if self._should_preserve(text):
                continue

            # First check for labeled amounts (high confidence): "Payment: $1000"
            labeled_match = self.LABELED_AMOUNT_PATTERN.search(text)
            if labeled_match:
                replacement = self._get_amount_replacement(text)
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="amount",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement=replacement,
                        confidence=0.95,
                        reason="Labeled monetary amount",
                    )
                )
            # Then check for standalone amounts (lower confidence)
            elif self.AMOUNT_PATTERN.search(text) and self._looks_like_amount(text):
                # Check for context clues
                context_score = self._check_context(text, text_blocks, block.page_num, block.bbox)

                # Mark as amount if looks like amount OR found context clues
                replacement = self._get_amount_replacement(text)
                # Higher confidence if we found context, lower if just pattern match
                confidence = (0.7 + (context_score * 0.3)) if context_score > 0 else 0.65
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="amount",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement=replacement,
                        confidence=confidence,
                        reason=f"Monetary amount (context score: {context_score:.1f})",
                    )
                )

        return detections

    def _should_preserve(self, text: str) -> bool:
        """Check if text matches preservation patterns."""
        for pattern in self.PRESERVE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _looks_like_amount(self, text: str) -> bool:
        """Check if text could be a monetary amount."""
        # Try to extract amount pattern from text
        match = self.AMOUNT_PATTERN.search(text)
        if not match:
            return False

        # Get the matched amount text
        amount_text = match.group(1).strip()

        # Must have at least one digit and decimal or comma
        if "." in amount_text or "," in amount_text:
            return True
        # Or be 3+ digits (could be amount like 100)
        if len(re.sub(r"\D", "", amount_text)) >= 3:
            return True

        return False

    def _check_context(self, text: str, blocks: list[TextBlock], page_num: int, bbox: tuple) -> float:
        """Check if surrounding text suggests this is an amount.

        Returns: Score 0.0-1.0
        """
        score = 0.0

        # Look at nearby text blocks for context
        for block in blocks:
            if block.page_num != page_num:
                continue

            # Check if text is very close (likely on same line)
            x_overlap = (
                max(0, min(bbox[2], block.bbox[2]) - max(bbox[0], block.bbox[0]))
            )
            if x_overlap > 0:  # Horizontal proximity
                label = block.text.lower()
                for context_word in self.AMOUNT_CONTEXT:
                    if context_word in label:
                        score = max(score, 0.8)
                        break

        return score

    def _get_amount_replacement(self, text: str) -> str:
        """Generate replacement for monetary amount."""
        # Preserve structure: if it had a comma, use comma; if it had decimals, preserve decimals
        has_decimal = "." in text
        has_comma = "," in text
        has_parens = text.startswith("(") and text.endswith(")")
        has_minus = "-" in text

        if has_decimal:
            # Standard $X.XX format
            replacement = "$0.00"
        elif has_comma:
            # Large amount with commas: $1,234,567.00 -> $0,000.00
            decimal_count = text.count(".")
            comma_count = text.count(",")
            if decimal_count == 1:
                replacement = "$0,000.00"
            else:
                replacement = "$0,000"
        else:
            # Integer amount
            replacement = "$0"

        if has_parens:
            replacement = f"({replacement})"
        elif has_minus:
            replacement = f"-{replacement}"

        return replacement

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get replacement for an amount."""
        return self._get_amount_replacement(text)
