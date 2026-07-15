from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass
class Transaction:
    transaction_date: date
    posting_date: date
    description: str
    amount: Decimal
    category: str
    reference_number: str | None = None
    merchant_location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_date": self.transaction_date.isoformat(),
            "posting_date": self.posting_date.isoformat(),
            "description": self.description,
            "amount": float(self.amount),
            "category": self.category,
            "reference_number": self.reference_number,
            "merchant_location": self.merchant_location,
        }


@dataclass
class AccountSummary:
    previous_balance: Decimal
    payments_credits: Decimal
    purchases_adjustments: Decimal
    fees: Decimal
    interest: Decimal
    new_balance: Decimal
    credit_limit: Decimal | None = None
    available_credit: Decimal | None = None
    cash_credit_line: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_balance": float(self.previous_balance),
            "payments_credits": float(self.payments_credits),
            "purchases_adjustments": float(self.purchases_adjustments),
            "fees": float(self.fees),
            "interest": float(self.interest),
            "new_balance": float(self.new_balance),
            "credit_limit": float(self.credit_limit) if self.credit_limit else None,
            "available_credit": float(self.available_credit) if self.available_credit else None,
            "cash_credit_line": float(self.cash_credit_line) if self.cash_credit_line else None,
        }


@dataclass
class InterestRate:
    balance_type: str
    apr: Decimal
    is_variable: bool
    balance_subject_to_interest: Decimal = Decimal("0")
    interest_charged: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance_type": self.balance_type,
            "apr": float(self.apr),
            "is_variable": self.is_variable,
            "balance_subject_to_interest": float(self.balance_subject_to_interest),
            "interest_charged": float(self.interest_charged),
        }


@dataclass
class RewardsSummary:
    base_earned: Decimal = Decimal("0")
    bonus_earned: Decimal = Decimal("0")
    relationship_bonus: Decimal = Decimal("0")
    total_available: Decimal = Decimal("0")
    reward_type: str = "cash_back"

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_earned": float(self.base_earned),
            "bonus_earned": float(self.bonus_earned),
            "relationship_bonus": float(self.relationship_bonus),
            "total_available": float(self.total_available),
            "reward_type": self.reward_type,
        }


@dataclass
class Statement:
    bank_name: str
    account_type: str
    account_number: str
    holder_name: str
    statement_period: tuple[date, date] | None
    closing_date: date | None
    summary: AccountSummary
    transactions: list[Transaction]
    payment_due_date: date | None = None
    minimum_payment: Decimal | None = None
    interest_rates: list[InterestRate] = field(default_factory=list)
    rewards: RewardsSummary | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_name": self.bank_name,
            "account_type": self.account_type,
            "account_number": self.account_number,
            "holder_name": self.holder_name,
            "statement_period_start": self.statement_period[0].isoformat() if self.statement_period else None,
            "statement_period_end": self.statement_period[1].isoformat() if self.statement_period else None,
            "closing_date": self.closing_date.isoformat() if self.closing_date else None,
            "payment_due_date": self.payment_due_date.isoformat() if self.payment_due_date else None,
            "minimum_payment": float(self.minimum_payment) if self.minimum_payment else None,
            "summary": self.summary.to_dict(),
            "transactions": [t.to_dict() for t in self.transactions],
            "interest_rates": [r.to_dict() for r in self.interest_rates],
            "rewards": self.rewards.to_dict() if self.rewards else None,
            "metadata": self.metadata,
        }
