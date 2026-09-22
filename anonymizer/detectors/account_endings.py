"""Detector for account number endings and masked account patterns."""

import re

from .base import Detector
from ..core.models import Detection, TextBlock


class AccountEndingsDetector(Detector):
    """Detects account number endings like 'Account Ending 7756' or 'XXXXXXXX7756'."""

    # Pattern for "Account Ending XXXX" format
    ACCOUNT_ENDING_LABEL = re.compile(
        r"account\s+ending\s+(\d{4})",
        re.IGNORECASE
    )

    # Pattern for masked accounts like "XXXXXXXX1234" or "****7756"
    MASKED_ACCOUNT = re.compile(
        r"(?:x{4,}|[\*]{4,})(\d{4})",
        re.IGNORECASE
    )

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect account ending patterns."""
        detections = []

        for block in text_blocks:
            text = self._normalize_text(block.text)

            # Skip very long blocks
            if len(text) > 100:
                continue

            # Check for "Account Ending XXXX"
            match = self.ACCOUNT_ENDING_LABEL.search(text)
            if match:
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="account_ending",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[ACCOUNT]",
                        confidence=0.9,
                        reason="Account ending with label detected",
                    )
                )
                continue

            # Check for masked account like "XXXXXXXX7756" or "****7756"
            match = self.MASKED_ACCOUNT.search(text)
            if match:
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="account_ending",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[ACCOUNT]",
                        confidence=0.85,
                        reason="Masked account number detected",
                    )
                )

        return detections

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get replacement for account ending."""
        return "[ACCOUNT]"
