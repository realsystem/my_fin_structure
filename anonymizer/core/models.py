"""Data models for anonymization detection and results."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Detection:
    """A detected sensitive field that should be anonymized."""

    detection_type: str
    """Type of detection: 'amount', 'name', 'address', 'account', 'routing', 'id', 'ssn', 'check', 'balance'"""

    bbox: tuple[float, float, float, float]
    """Bounding box: (x0, y0, x1, y1) in PDF coordinates"""

    page_num: int
    """0-indexed page number"""

    original_text: Optional[str]
    """Original text (NOT stored in public JSON; internal only)"""

    replacement: str
    """Sanitized replacement value"""

    confidence: float
    """Confidence score 0.0-1.0"""

    reason: str
    """Explanation of why this was detected"""

    is_context: bool = False
    """If True, this is context (e.g., label) and may be kept"""

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict WITHOUT original sensitive values."""
        return {
            "type": self.detection_type,
            "page": self.page_num,
            "bbox": list(self.bbox),
            "replacement": self.replacement,
            "confidence": self.confidence,
            "reason": self.reason,
            "is_context": self.is_context,
        }


@dataclass
class TextBlock:
    """A text block extracted from PDF with its position."""

    text: str
    """The text content"""

    bbox: tuple[float, float, float, float]
    """Bounding box: (x0, y0, x1, y1)"""

    page_num: int
    """0-indexed page number"""

    font_name: Optional[str] = None
    font_size: Optional[float] = None
    is_bold: bool = False


@dataclass
class AnonymizationResult:
    """Result of anonymizing a PDF."""

    input_path: str
    output_path: str
    pages_total: int
    detections: list[Detection]
    text_blocks: list[TextBlock]
    pdf_metadata: dict

    def to_inspection_dict(self) -> dict:
        """Convert to inspection JSON (safe for sharing)."""
        return {
            "input": self.input_path,
            "output": self.output_path,
            "pages": self.pages_total,
            "detections": [d.to_dict() for d in self.detections],
            "text_blocks": [
                {
                    "page": tb.page_num,
                    "bbox": list(tb.bbox),
                    "text_preview": tb.text[:50] if len(tb.text) <= 50 else tb.text[:47] + "...",
                    "font": tb.font_name,
                    "size": tb.font_size,
                }
                for tb in self.text_blocks
            ],
            "pdf_metadata": self.pdf_metadata,
        }
