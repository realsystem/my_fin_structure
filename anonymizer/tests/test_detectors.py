"""Tests for anonymization detectors."""

import pytest

from anonymizer.core.models import TextBlock
from anonymizer.detectors import (
    AmountDetector,
    NameDetector,
    AddressDetector,
    AccountNumberDetector,
    AccountEndingsDetector,
    IdentifierDetector,
    DateDetector,
)


class TestAmountDetector:
    """Test monetary amount detection."""

    def test_detects_dollar_amounts(self):
        """Detect standard dollar amounts."""
        detector = AmountDetector()
        block = TextBlock(
            text="$1,234.56",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "amount"
        assert detections[0].replacement == "$0.00"

    def test_preserves_dates(self):
        """Don't anonymize dates."""
        detector = AmountDetector()
        block = TextBlock(
            text="01/15/2026",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        # Should not be detected as amount
        assert len(detections) == 0

    def test_preserves_page_numbers(self):
        """Don't anonymize page numbers."""
        detector = AmountDetector()
        block = TextBlock(
            text="Page 2 of 5",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) == 0


class TestAccountNumberDetector:
    """Test account number detection."""

    def test_detects_account_with_label(self):
        """Detect account numbers with explicit label."""
        detector = AccountNumberDetector()
        block = TextBlock(
            text="Account Number: 123456789012345",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "account"

    def test_detects_routing_number(self):
        """Detect routing numbers."""
        detector = AccountNumberDetector()
        block = TextBlock(
            text="Routing Number: 021000021",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "routing"

    def test_detects_check_number(self):
        """Detect check numbers."""
        detector = AccountNumberDetector()
        block = TextBlock(
            text="Check Number: 1234",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "check"


class TestNameDetector:
    """Test personal name detection."""

    def test_detects_common_names(self):
        """Detect common first and last name combinations."""
        detector = NameDetector()
        block = TextBlock(
            text="John Smith",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "name"
        assert detections[0].replacement == "[NAME]"

    def test_detects_custom_names(self):
        """Detect user-provided custom names."""
        detector = NameDetector(custom_names=["Alice Johnson", "Bob Wilson"])

        # Test exact match (case-insensitive)
        block = TextBlock(
            text="alice johnson",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "name"

        # Test another custom name
        block = TextBlock(
            text="Bob Wilson",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0

    def test_custom_names_take_precedence(self):
        """Custom names should be detected even if not in common names list."""
        detector = NameDetector(custom_names=["Zxyzzy Quux"])
        block = TextBlock(
            text="Zxyzzy Quux",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0


class TestAddressDetector:
    """Test address detection."""

    def test_detects_street_address(self):
        """Detect street addresses."""
        detector = AddressDetector()
        block = TextBlock(
            text="123 Main Street",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "address"

    def test_detects_city_state_zip(self):
        """Detect city, state, zip."""
        detector = AddressDetector()
        block = TextBlock(
            text="San Francisco, CA 94102",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "address"


class TestIdentifierDetector:
    """Test government ID detection."""

    def test_detects_ssn(self):
        """Detect Social Security Numbers."""
        detector = IdentifierDetector()
        block = TextBlock(
            text="SSN: 123-45-6789",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "ssn"
        assert detections[0].replacement == "[SSN]"


class TestAccountEndingsDetector:
    """Test account ending detection."""

    def test_detects_account_ending_label(self):
        """Detect 'Account Ending XXXX' pattern."""
        detector = AccountEndingsDetector()
        block = TextBlock(
            text="Account Ending 7756",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "account_ending"
        assert detections[0].replacement == "[ACCOUNT]"
        assert detections[0].confidence == 0.9

    def test_detects_masked_account_x_format(self):
        """Detect masked account like XXXXXXXX7756."""
        detector = AccountEndingsDetector()
        block = TextBlock(
            text="XXXXXXXX7756",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "account_ending"
        assert detections[0].replacement == "[ACCOUNT]"

    def test_detects_masked_account_asterisk_format(self):
        """Detect masked account like ****7756."""
        detector = AccountEndingsDetector()
        block = TextBlock(
            text="****7756",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0
        assert detections[0].detection_type == "account_ending"

    def test_detects_account_ending_case_insensitive(self):
        """Account ending label should be case-insensitive."""
        detector = AccountEndingsDetector()
        block = TextBlock(
            text="account ending 1234",
            bbox=(0, 0, 100, 20),
            page_num=0,
        )
        detections = detector.detect([block])
        assert len(detections) > 0


class TestDateDetector:
    """Test date handling."""

    def test_preserves_dates(self):
        """Dates should not be anonymized."""
        detector = DateDetector()
        # Detector should be empty (dates preserved)
        assert detector.detect([]) == []

    def test_identifies_dates(self):
        """Should be able to identify dates."""
        detector = DateDetector()
        assert detector.is_date("01/15/2026")
        assert detector.is_date("January 15, 2026")
        assert detector.is_date("2026-01-15")
