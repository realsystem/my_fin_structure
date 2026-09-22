"""Detector for account numbers, routing numbers, and financial identifiers."""

import re

from .base import Detector
from ..core.models import Detection, TextBlock


class AccountNumberDetector(Detector):
    """Detects account numbers, routing numbers, and financial IDs."""

    # Bank account number patterns (typically 8-17 digits)
    ACCOUNT_PATTERN = re.compile(r"\b\d{8,17}\b")

    # Routing number pattern (9 digits)
    ROUTING_PATTERN = re.compile(r"\b\d{9}\b")

    # Account number with account label
    ACCOUNT_LABEL_PATTERN = re.compile(
        r"(?:account\s*(?:number|#|no\.?)|acct\s*(?:number|#|no\.?))\s*:?\s*(\d{8,17})",
        re.IGNORECASE
    )

    # Routing number with label
    ROUTING_LABEL_PATTERN = re.compile(
        r"(?:routing\s*(?:number|#|no\.?))\s*:?\s*(\d{9})",
        re.IGNORECASE
    )

    # Check number (usually short)
    CHECK_PATTERN = re.compile(r"(?:check\s*(?:number|#|no\.?))\s*:?\s*(\d{4,7})", re.IGNORECASE)

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect account numbers and financial identifiers."""
        detections = []

        for block in text_blocks:
            text = self._normalize_text(block.text)

            # Check for explicit account number labels first
            account_match = re.search(self.ACCOUNT_LABEL_PATTERN, text)
            if account_match:
                account_num = account_match.group(1)
                detections.append(
                    self._log_detection(
                        text=account_num,
                        detection_type="account",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[ACCOUNT]",
                        confidence=0.95,
                        reason="Account number with label detected",
                    )
                )
                continue

            # Check for routing number
            routing_match = re.search(self.ROUTING_LABEL_PATTERN, text)
            if routing_match:
                routing_num = routing_match.group(1)
                detections.append(
                    self._log_detection(
                        text=routing_num,
                        detection_type="routing",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[ROUTING]",
                        confidence=0.95,
                        reason="Routing number detected",
                    )
                )
                continue

            # Check for check number
            check_match = re.search(self.CHECK_PATTERN, text)
            if check_match:
                check_num = check_match.group(1)
                detections.append(
                    self._log_detection(
                        text=check_num,
                        detection_type="check",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[CHECK]",
                        confidence=0.9,
                        reason="Check number detected",
                    )
                )
                continue

            # Look for standalone account-like numbers (8-17 digits)
            # But be conservative - only flag if very likely
            if len(text) >= 8 and re.match(r"^\d{8,17}$", text):
                # Only flag if it's in a position/format that looks like account number
                if self._looks_like_account_context(text):
                    detections.append(
                        self._log_detection(
                            text=text,
                            detection_type="account",
                            bbox=block.bbox,
                            page_num=block.page_num,
                            replacement="[ACCOUNT]",
                            confidence=0.6,
                            reason="Long numeric sequence (possible account number)",
                        )
                    )

        return detections

    def _looks_like_account_context(self, text: str) -> bool:
        """Check if standalone number looks like it could be an account."""
        # 12-17 digits is very likely account (not date, page number, etc)
        return len(text) >= 12

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get replacement for account/routing/check numbers."""
        if detection_type == "routing":
            return "[ROUTING]"
        elif detection_type == "check":
            return "[CHECK]"
        else:  # account or unknown
            return "[ACCOUNT]"
