from abc import ABC, abstractmethod
from pathlib import Path

from src.core.models import Statement


class StatementProvider(ABC):
    name: str
    bank_id: str

    @abstractmethod
    def can_parse(self, text: str, pages: list[str]) -> float:
        """Return confidence score 0-1 that this provider can parse the document."""

    @abstractmethod
    def parse(self, text: str, pages: list[str]) -> Statement:
        """Extract Statement from PDF content."""


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: list[StatementProvider] = []

    def register(self, provider: StatementProvider) -> None:
        self._providers.append(provider)

    def find_provider(self, text: str, pages: list[str]) -> StatementProvider | None:
        best_provider = None
        best_score = 0.0

        for provider in self._providers:
            score = provider.can_parse(text, pages)
            if score > best_score:
                best_score = score
                best_provider = provider

        if best_score < 0.5:
            return None
        return best_provider

    def parse(self, text: str, pages: list[str]) -> Statement:
        provider = self.find_provider(text, pages)
        if provider is None:
            raise ValueError("No provider found that can parse this document")
        return provider.parse(text, pages)

    @property
    def providers(self) -> list[StatementProvider]:
        return self._providers.copy()


registry = ProviderRegistry()


def register_provider(provider: StatementProvider) -> None:
    registry.register(provider)


def load_providers() -> None:
    from src.providers import bofa_credit
    from src.providers import citi
    from src.providers import chase
    from src.providers import bank_of_america
    from src.providers import american_express