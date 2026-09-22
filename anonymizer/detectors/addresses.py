"""Detector for mailing addresses."""

import re

from .base import Detector
from ..core.models import Detection, TextBlock


class AddressDetector(Detector):
    """Detects street addresses and mailing addresses."""

    # Address line patterns
    ADDRESS_PATTERN = re.compile(
        r"^\d+\s+[\w\s]+(?:street|st|avenue|ave|road|rd|drive|dr|circle|ct|court|blvd|boulevard|lane|ln|way|terrace|tr|place|pl|park|parkway|pkwy)\b",
        re.IGNORECASE
    )

    # City, State ZIP patterns
    CITY_STATE_ZIP_PATTERN = re.compile(
        r"^([A-Za-z][a-zA-Z\s]+),\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$"
    )

    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect mailing addresses."""
        detections = []

        for i, block in enumerate(text_blocks):
            text = self._normalize_text(block.text)

            # Check for street address
            if self._is_street_address(text):
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="address",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[ADDRESS]",
                        confidence=0.8,
                        reason="Street address detected",
                    )
                )
            # Check for city, state, zip
            elif self._is_city_state_zip(text):
                detections.append(
                    self._log_detection(
                        text=text,
                        detection_type="address",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[CITY, STATE ZIP]",
                        confidence=0.85,
                        reason="City, state, ZIP detected",
                    )
                )

        return detections

    def _is_street_address(self, text: str) -> bool:
        """Check if text is a street address line."""
        return bool(re.match(self.ADDRESS_PATTERN, text))

    def _is_city_state_zip(self, text: str) -> bool:
        """Check if text is city, state, zip format."""
        return bool(re.match(self.CITY_STATE_ZIP_PATTERN, text))

    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get replacement for address."""
        if self._is_city_state_zip(text):
            return "[CITY, STATE ZIP]"
        return "[ADDRESS]"
