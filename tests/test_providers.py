"""Tests for bank statement providers."""
import pytest
from decimal import Decimal
from pathlib import Path

from src.providers.base import load_providers, registry
from src.utils.pdf import extract_text


@pytest.fixture(scope="module", autouse=True)
def setup_providers():
    """Load all providers before tests."""
    load_providers()


class TestBofaCreditProvider:
    """Tests for Bank of America credit card provider."""

    @pytest.fixture
    def pdf_path(self):
        path = Path("eStmt_2026-06-19.pdf")
        if not path.exists():
            pytest.skip("BoFA test PDF not found")
        return path

    @pytest.fixture
    def statement(self, pdf_path):
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "bofa_credit"
        return provider.parse(text, pages)

    def test_detection(self, pdf_path):
        """Provider should detect BoFA credit card statement."""
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "bofa_credit"
        assert provider.can_parse(text, pages) >= 0.5

    def test_account_info(self, statement):
        """Should extract account information."""
        assert statement.bank_name == "Bank of America"
        assert statement.account_type == "credit_card"
        assert len(statement.account_number) >= 4

    def test_statement_period(self, statement):
        """Should extract statement period dates."""
        start, end = statement.statement_period
        assert start < end
        assert start.year >= 2020

    def test_transactions_extracted(self, statement):
        """Should extract transactions."""
        assert len(statement.transactions) > 0

    def test_transaction_categories(self, statement):
        """Each transaction should have a valid category."""
        valid_categories = {"payment", "purchase", "interest", "fee", "adjustment"}
        for txn in statement.transactions:
            assert txn.category in valid_categories

    def test_summary(self, statement):
        """Should extract account summary."""
        assert statement.summary is not None


class TestCitiProvider:
    """Tests for Citi credit card provider."""

    @pytest.fixture
    def pdf_path(self):
        path = Path("citi_10-18-2019.pdf")
        if not path.exists():
            pytest.skip("Citi test PDF not found")
        return path

    @pytest.fixture
    def statement(self, pdf_path):
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "citi"
        return provider.parse(text, pages)

    def test_detection(self, pdf_path):
        """Provider should detect Citi statement."""
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "citi"
        assert provider.can_parse(text, pages) >= 0.5

    def test_account_info(self, statement):
        """Should extract account information."""
        assert statement.bank_name == "Citi"
        assert statement.account_type == "credit_card"
        assert len(statement.account_number) >= 4

    def test_statement_period(self, statement):
        """Should extract statement period dates."""
        start, end = statement.statement_period
        assert start < end

    def test_transactions_extracted(self, statement):
        """Should extract transactions."""
        assert len(statement.transactions) > 0

    def test_transaction_descriptions(self, statement):
        """Transactions should have meaningful descriptions."""
        for txn in statement.transactions:
            assert txn.description
            assert len(txn.description) > 3

    def test_summary(self, statement):
        """Should extract account summary."""
        assert statement.summary is not None


class TestChaseProvider:
    """Tests for Chase credit card provider."""

    @pytest.fixture
    def pdf_path(self):
        path = Path("20260619-statements-1490-.pdf")
        if not path.exists():
            pytest.skip("Chase test PDF not found")
        return path

    @pytest.fixture
    def statement(self, pdf_path):
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "chase"
        return provider.parse(text, pages)

    def test_detection(self, pdf_path):
        """Provider should detect Chase statement."""
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        assert provider is not None
        assert provider.bank_id == "chase"
        assert provider.can_parse(text, pages) >= 0.5

    def test_account_info(self, statement):
        """Should extract account information."""
        assert statement.bank_name == "CHASE"
        assert statement.account_type == "credit_card"

    def test_transactions_extracted(self, statement):
        """Should extract transactions."""
        assert len(statement.transactions) > 0

    def test_transaction_categories(self, statement):
        """Each transaction should have a valid category."""
        valid_categories = {"payment", "purchase", "interest", "fee", "adjustment"}
        for txn in statement.transactions:
            assert txn.category in valid_categories


class TestProviderRegistry:
    """Tests for provider registry functionality."""

    def test_providers_loaded(self):
        """Registry should have providers loaded."""
        assert len(registry.providers) >= 2

    def test_find_provider_returns_none_for_unknown(self):
        """Should return None for unrecognized documents."""
        provider = registry.find_provider("random text content", ["random text"])
        assert provider is None

    def test_provider_confidence_threshold(self):
        """Provider should only match above 0.5 confidence."""
        for provider in registry.providers:
            score = provider.can_parse("", [])
            assert score < 0.5
