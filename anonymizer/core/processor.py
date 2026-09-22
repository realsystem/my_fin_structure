"""PDF processing and anonymization logic."""

import json
import logging
from pathlib import Path
from typing import Optional, Tuple
import io

try:
    import pdfplumber
    import fitz  # PyMuPDF
    HAS_MUPDF = True
except ImportError:
    HAS_MUPDF = False

from ..core.models import Detection, TextBlock, AnonymizationResult
from ..detectors import (
    AmountDetector,
    NameDetector,
    AddressDetector,
    AccountNumberDetector,
    AccountEndingsDetector,
    IdentifierDetector,
    DateDetector,
)


logger = logging.getLogger(__name__)


class PDFAnonymizer:
    """Anonymizes bank statement PDFs."""

    def __init__(self, custom_names: list[str] | None = None):
        """Initialize anonymizer with detectors.

        Args:
            custom_names: Optional list of names to anonymize
        """
        self.detectors = [
            IdentifierDetector(),  # Check these first (high confidence)
            AccountNumberDetector(),
            AccountEndingsDetector(),
            NameDetector(custom_names=custom_names),
            AddressDetector(),
            AmountDetector(),  # More prone to false positives
        ]
        self.date_detector = DateDetector()

    def anonymize(
        self,
        input_pdf: Path,
        output_pdf: Path,
        create_inspection_file: bool = True,
    ) -> AnonymizationResult:
        """Anonymize a PDF and optionally create inspection file.

        Args:
            input_pdf: Path to original PDF
            output_pdf: Path where anonymized PDF will be written
            create_inspection_file: Whether to create a .json inspection file

        Returns:
            AnonymizationResult with detections and metadata
        """
        if not HAS_MUPDF:
            raise ImportError(
                "PyMuPDF (fitz) is required for PDF anonymization. "
                "Install with: pip install PyMuPDF"
            )

        if not input_pdf.exists():
            raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

        logger.info(f"Anonymizing {input_pdf}...")

        # Extract text blocks from PDF
        text_blocks = self._extract_text_blocks(input_pdf)
        logger.info(f"Extracted {len(text_blocks)} text blocks")

        # Detect sensitive information
        all_detections = []
        for detector in self.detectors:
            detections = detector.detect(text_blocks)
            all_detections.extend(detections)
            logger.info(f"{detector.__class__.__name__} found {len(detections)} items")

        # Remove duplicate/overlapping detections (keep highest confidence)
        all_detections = self._deduplicate_detections(all_detections)
        logger.info(f"After deduplication: {len(all_detections)} detections")

        # Generate anonymized PDF
        self._create_anonymized_pdf(
            input_pdf, output_pdf, all_detections
        )
        logger.info(f"Anonymized PDF written to {output_pdf}")

        # Get PDF metadata
        metadata = self._get_pdf_metadata(input_pdf)

        # Create result
        result = AnonymizationResult(
            input_path=str(input_pdf),
            output_path=str(output_pdf),
            pages_total=metadata.get("pages", 0),
            detections=all_detections,
            text_blocks=text_blocks,
            pdf_metadata=metadata,
        )

        # Optionally create inspection file
        if create_inspection_file:
            inspection_path = output_pdf.with_suffix(".json")
            self._write_inspection_file(result, inspection_path)
            logger.info(f"Inspection file written to {inspection_path}")

        return result

    def _extract_text_blocks(self, pdf_path: Path) -> list[TextBlock]:
        """Extract text blocks with precise character-level positions from PDF."""
        text_blocks = []

        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc):
                # Use get_text with "dict" to get detailed layout
                layout = page.get_text("dict")

                for block in layout["blocks"]:
                    # Skip non-text blocks
                    if block["type"] != 0:
                        continue

                    # Extract lines and their bounding boxes
                    for line in block.get("lines", []):
                        line_text = ""
                        line_bbox = None

                        for span in line.get("spans", []):
                            text = span.get("text", "")
                            if not text:
                                continue

                            # Get bbox for this span
                            bbox = span.get("bbox")
                            if bbox:
                                x0, y0, x1, y1 = bbox

                                # Initialize line bbox or expand it
                                if line_bbox is None:
                                    line_bbox = [x0, y0, x1, y1]
                                else:
                                    line_bbox[0] = min(line_bbox[0], x0)
                                    line_bbox[1] = min(line_bbox[1], y0)
                                    line_bbox[2] = max(line_bbox[2], x1)
                                    line_bbox[3] = max(line_bbox[3], y1)

                            line_text += text

                        # Add line as a text block with accurate bbox
                        if line_text.strip() and line_bbox:
                            text_blocks.append(
                                TextBlock(
                                    text=line_text.strip(),
                                    bbox=tuple(line_bbox),
                                    page_num=page_num,
                                )
                            )

        return text_blocks

    def _deduplicate_detections(self, detections: list[Detection]) -> list[Detection]:
        """Remove overlapping detections, keeping highest confidence."""
        if not detections:
            return []

        # Sort by confidence descending
        sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)

        result = []
        used_regions = []

        for det in sorted_dets:
            # Check if this detection overlaps with any already accepted
            if not self._overlaps_any(det.bbox, det.page_num, used_regions):
                result.append(det)
                used_regions.append((det.bbox, det.page_num))

        return result

    def _overlaps_any(
        self,
        bbox: Tuple[float, float, float, float],
        page_num: int,
        used_regions: list,
    ) -> bool:
        """Check if bbox overlaps with any used region on same page."""
        for used_bbox, used_page in used_regions:
            if used_page != page_num:
                continue

            # Check intersection
            if self._bboxes_overlap(bbox, used_bbox):
                return True

        return False

    @staticmethod
    def _bboxes_overlap(
        box1: Tuple[float, float, float, float],
        box2: Tuple[float, float, float, float],
    ) -> bool:
        """Check if two bboxes overlap."""
        x0_1, y0_1, x1_1, y1_1 = box1
        x0_2, y0_2, x1_2, y1_2 = box2

        # No overlap if one is completely to the left/right/above/below the other
        if x1_1 <= x0_2 or x1_2 <= x0_1:
            return False
        if y1_1 <= y0_2 or y1_2 <= y0_1:
            return False

        return True

    def _create_anonymized_pdf(
        self,
        input_path: Path,
        output_path: Path,
        detections: list[Detection],
    ) -> None:
        """Create anonymized PDF by replacing detected text."""
        with fitz.open(input_path) as doc:
            for detection in detections:
                page = doc[detection.page_num]

                # Find and replace the text in the PDF
                # Note: This is a simplified approach; a full implementation
                # might need to handle text location more precisely
                self._replace_text_in_page(
                    page, detection.bbox, detection.replacement
                )

            # Write output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(output_path)

    def _replace_text_in_page(
        self,
        page,
        bbox: Tuple[float, float, float, float],
        replacement: str,
    ) -> None:
        """Replace text in a specific location on a page."""
        # Get the region and add a white rectangle with replacement text
        x0, y0, x1, y1 = bbox

        # Draw white rectangle to cover original text
        page.draw_rect(bbox, color=None, fill=(1, 1, 1), width=0)

        # Add replacement text
        # Calculate font size to fit roughly in the same space
        text_width = x1 - x0
        text_height = y1 - y0
        font_size = max(8, min(12, text_height - 2))

        # Insert replacement text
        page.insert_text(
            (x0 + 2, y0 + text_height / 2),
            replacement,
            fontsize=font_size,
            color=(0, 0, 0),
        )

    def _get_pdf_metadata(self, pdf_path: Path) -> dict:
        """Extract metadata from PDF."""
        metadata = {
            "pages": 0,
            "title": None,
            "creator": None,
            "producer": None,
        }

        with fitz.open(pdf_path) as doc:
            metadata["pages"] = len(doc)
            if doc.metadata:
                metadata["title"] = doc.metadata.get("title")
                metadata["creator"] = doc.metadata.get("creator")
                metadata["producer"] = doc.metadata.get("producer")

        return metadata

    def _write_inspection_file(
        self, result: AnonymizationResult, output_path: Path
    ) -> None:
        """Write inspection file with anonymization details."""
        inspection_data = result.to_inspection_dict()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(inspection_data, f, indent=2)

    def inspect_pdf(self, pdf_path: Path) -> None:
        """Inspect a PDF without creating anonymized version.

        Useful for understanding structure before full anonymization.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info(f"Inspecting {pdf_path}...")

        text_blocks = self._extract_text_blocks(pdf_path)
        logger.info(f"Found {len(text_blocks)} text blocks")

        # Detect sensitive information
        all_detections = []
        for detector in self.detectors:
            detections = detector.detect(text_blocks)
            all_detections.extend(detections)

        all_detections = self._deduplicate_detections(all_detections)

        metadata = self._get_pdf_metadata(pdf_path)

        result = AnonymizationResult(
            input_path=str(pdf_path),
            output_path="(not written)",
            pages_total=metadata.get("pages", 0),
            detections=all_detections,
            text_blocks=text_blocks,
            pdf_metadata=metadata,
        )

        # Print inspection summary
        logger.info(f"\n=== PDF Inspection ===")
        logger.info(f"Pages: {result.pages_total}")
        logger.info(f"Text blocks: {len(result.text_blocks)}")
        logger.info(f"Detections: {len(result.detections)}")

        for det_type in set(d.detection_type for d in result.detections):
            count = sum(1 for d in result.detections if d.detection_type == det_type)
            logger.info(f"  {det_type}: {count}")

        return result
