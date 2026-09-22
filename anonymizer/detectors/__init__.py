"""Sensitive data detectors for bank statements."""

from .base import Detector
from .amounts import AmountDetector
from .names import NameDetector
from .addresses import AddressDetector
from .account_numbers import AccountNumberDetector
from .account_endings import AccountEndingsDetector
from .identifiers import IdentifierDetector
from .dates import DateDetector

__all__ = [
    "Detector",
    "AmountDetector",
    "NameDetector",
    "AddressDetector",
    "AccountNumberDetector",
    "AccountEndingsDetector",
    "IdentifierDetector",
    "DateDetector",
]
