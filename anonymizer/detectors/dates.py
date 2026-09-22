"""Detector for dates and related temporal information."""

import re

from .base import Detector
from ..core.models import Detection, TextBlock


class DateDetector(Detector):
    """Detects dates (note: dates are usually PRESERVED, not anonymized)."""

    # Date patterns that should be PRESERVED
    DATE_FORMATS = [
        r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/\d{2,4}\b",  # M/D/YYYY
        r"\b(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])/\d{2,4}\b",  # D/M/YYYY
        r"\b\d{4}-(?:0?[1-9]|1[0-2])-(?:0?[1-9]|[12]\d|3[01])\b",  # YYYY-MM-DD
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
    ]

    DATE_PATTERN = re.compile("|".join(f"({fmt})" for fmt in DATE_FORMATS), re.IGNORECASE)

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Dates are typically preserved, not anonymized.

        This detector only marks dates that are part of larger sensitive strings
        that shouldn't be preserved.
        """
        # Dates are generally safe and should be preserved
        # This detector is here for completeness but doesn't flag anything
        return []

    def is_date(self, text: str) -> bool:
        """Check if text is a date (for use by other detectors)."""
        return bool(re.search(self.DATE_PATTERN, text.strip()))

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Dates are not replaced."""
        return text  # Keep original
