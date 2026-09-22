"""Detector for SSN, government IDs, and other identifiers."""

import re

from .base import Detector
from ..core.models import Detection, TextBlock


class IdentifierDetector(Detector):
    """Detects SSN, government IDs, and similar identifiers."""

    # Social Security Number: XXX-XX-XXXX
    SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

    # SSN variants without dashes
    SSN_NODASH_PATTERN = re.compile(r"\b\d{9}\b(?:\s+|$)")

    # Driver's license (rough pattern)
    DL_PATTERN = re.compile(
        r"(?:driver's?\s*license|dl)\s*(?:number|#|no\.?)?\s*:?\s*([A-Z0-9]{5,20})",
        re.IGNORECASE
    )

    # EIN (employer ID)
    EIN_PATTERN = re.compile(r"\d{2}-\d{7}")

    # Tax ID
    TAX_ID_PATTERN = re.compile(
        r"(?:tax\s*id|tin)\s*:?\s*(\d{2}-\d{7}|\d{3}-\d{2}-\d{4})",
        re.IGNORECASE
    )

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect government IDs and identifiers."""
        detections = []

        for block in text_blocks:
            text = self._normalize_text(block.text)

            # Check for SSN patterns
            ssn_match = re.search(self.SSN_PATTERN, text)
            if ssn_match:
                detections.append(
                    self._log_detection(
                        text=ssn_match.group(0),
                        detection_type="ssn",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[SSN]",
                        confidence=0.95,
                        reason="Social Security Number detected",
                    )
                )
                continue

            # Check for EIN
            ein_match = re.search(self.EIN_PATTERN, text)
            if ein_match:
                detections.append(
                    self._log_detection(
                        text=ein_match.group(0),
                        detection_type="id",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[ID]",
                        confidence=0.85,
                        reason="Employer ID (EIN) detected",
                    )
                )
                continue

            # Check for tax ID
            tax_match = re.search(self.TAX_ID_PATTERN, text)
            if tax_match:
                detections.append(
                    self._log_detection(
                        text=tax_match.group(1),
                        detection_type="id",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[TAX ID]",
                        confidence=0.9,
                        reason="Tax ID detected",
                    )
                )
                continue

            # Check for driver's license
            dl_match = re.search(self.DL_PATTERN, text)
            if dl_match:
                detections.append(
                    self._log_detection(
                        text=dl_match.group(1),
                        detection_type="id",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[DL#]",
                        confidence=0.85,
                        reason="Driver's license number detected",
                    )
                )

        return detections

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get replacement for identifier."""
        if detection_type == "ssn":
            return "[SSN]"
        else:
            return "[ID]"
