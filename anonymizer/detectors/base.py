"""Base detector class and utilities."""

from abc import ABC, abstractmethod
from typing import Optional

from ..core.models import Detection, TextBlock


class Detector(ABC):
    """Base class for sensitive data detectors."""

    @abstractmethod
    def detect(self, text_blocks: list[TextBlock]) -> list[Detection]:
        """Detect sensitive elements in text blocks.

        Args:
            text_blocks: List of text blocks with positions

        Returns:
            List of Detection objects for sensitive fields found
        """
        pass

    @abstractmethod
    def get_replacement(self, text: str, detection_type: str) -> str:
        """Get appropriate replacement for detected text.

        Args:
            text: Original text
            detection_type: Type of detection

        Returns:
            Sanitized replacement string
        """
        pass

    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching."""
        return text.strip()

    def _log_detection(
        self,
        text: str,
        detection_type: str,
        bbox: tuple,
        page_num: int,
        replacement: str,
        confidence: float,
        reason: str,
        is_context: bool = False,
    ) -> Detection:
        """Create a Detection object (with sanitized original)."""
        return Detection(
            detection_type=detection_type,
            bbox=bbox,
            page_num=page_num,
            original_text=None,  # Never store original in object
            replacement=replacement,
            confidence=confidence,
            reason=reason,
            is_context=is_context,
        )
