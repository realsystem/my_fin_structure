"""Detector for personal names."""

import re

from .base import Detector
from ..core.models import Detection, TextBlock


class NameDetector(Detector):
    """Detects personal names in bank statements."""

    # Common first names
    COMMON_FIRST_NAMES = {
        "james", "john", "robert", "michael", "william", "david", "richard", "joseph",
        "thomas", "charles", "mary", "patricia", "jennifer", "linda", "barbara",
        "elizabeth", "susan", "jessica", "sarah", "karen", "nancy", "andrew", "thomas",
    }

    # Common last name patterns
    LAST_NAME_PATTERNS = [
        r"\bsmith\b",
        r"\bjohnson\b",
        r"\bwilliams\b",
        r"\bjones\b",
        r"\bbrown\b",
        r"\bgarcía\b",
        r"\bmiller\b",
        r"\bdavis\b",
        r"\bmoore\b",
        r"\btaylor\b",
    ]

    def __init__(self, custom_names: list[str] | None = None):
        """Initialize with optional custom names to detect.

        Args:
            custom_names: List of names to detect (in addition to common names)
        """
        super().__init__()
        self.custom_names = set(n.lower() for n in (custom_names or []))

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect personal names."""
        detections = []

        for block in text_blocks:
            text = self._normalize_text(block.text)

            # Skip if too long (unlikely to be just a name)
            if len(text) > 60:
                continue

            # Look for patterns like "FirstName LastName"
            # Two capitalized words, potentially separated by whitespace
            if self._looks_like_name(text):
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="name",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[NAME]",
                        confidence=0.7,
                        reason="Personal name detected",
                    )
                )

        return detections

    def _looks_like_name(self, text: str) -> bool:
        """Check if text looks like a personal name."""
        # Check custom names first (exact match, case-insensitive)
        text_lower = text.lower()
        if text_lower in self.custom_names:
            return True

        parts = text.split()

        # Two parts, both starting with capital
        if len(parts) == 2:
            if parts[0][0].isupper() and parts[1][0].isupper():
                # Check against known first/last names
                first_lower = parts[0].lower()
                last_lower = parts[1].lower()

                if first_lower in self.COMMON_FIRST_NAMES:
                    return True
                for pattern in self.LAST_NAME_PATTERNS:
                    if re.search(pattern, last_lower, re.IGNORECASE):
                        return True

        return False

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get replacement for a name."""
        return "[NAME]"
