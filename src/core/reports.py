import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.core.models import Transaction


@dataclass
class TransactionFilter:
    merchant: str | None = None
    category: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None


@dataclass
class MerchantSummary:
    name: str
    total: Decimal
    count: int
    average: Decimal
    date_range: tuple[date, date]
    transactions: list[Transaction]
    by_location: dict[str, tuple[Decimal, int]] = field(default_factory=dict)


def extract_merchant_info(description: str) -> tuple[str, str | None]:
    """Extract merchant name and location from transaction description.

    Examples:
        "LOWES #02661* FERNLEY NV" -> ("LOWES", "FERNLEY NV")
        "THE HOME DEPOT #1076 BRENTWOOD CA" -> ("HOME DEPOT", "BRENTWOOD CA")
        "HARBOR FREIGHT TOOLS3337 ANTIOCH CA" -> ("HARBOR FREIGHT", "ANTIOCH CA")
        "HOMEDEPOT.COM HOMEDEPOT.COMGA" -> ("HOMEDEPOT.COM", "HOMEDEPOT.COMGA")
    """
    desc = description.strip()

    patterns = [
        r"^(THE\s+)?(.+?)\s*#\d+\*?\s+(.+)$",
        r"^(.+?)\s*TOOLS?\d+\s+(.+)$",
        r"^(.+?)\s+(\d{3}-\d{3}-\d{4}\s+\w+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, desc, re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                merchant = groups[1].strip()
                location = groups[2].strip()
            else:
                merchant = groups[0].strip()
                location = groups[1].strip() if len(groups) > 1 else None
            return merchant.upper(), location

    parts = desc.split()
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isupper():
        location = f"{parts[-2]} {parts[-1]}"
        merchant = " ".join(parts[:-2]) if len(parts) > 2 else parts[0]
        return merchant.upper(), location

    return desc.upper(), None


class ReportGenerator:
    def filter(
        self, transactions: list[Transaction], f: TransactionFilter
    ) -> list[Transaction]:
        result = []

        for txn in transactions:
            if f.merchant:
                merchant_name, _ = extract_merchant_info(txn.description)
                if f.merchant.upper() not in merchant_name and f.merchant.upper() not in txn.description.upper():
                    continue

            if f.category and txn.category != f.category:
                continue

            if f.date_from and txn.transaction_date < f.date_from:
                continue

            if f.date_to and txn.transaction_date > f.date_to:
                continue

            amount = abs(txn.amount)
            if f.min_amount is not None and amount < f.min_amount:
                continue

            if f.max_amount is not None and amount > f.max_amount:
                continue

            result.append(txn)

        return sorted(result, key=lambda t: t.transaction_date)

    def merchant_summary(
        self, transactions: list[Transaction], merchant: str
    ) -> MerchantSummary:
        filtered = self.filter(
            transactions, TransactionFilter(merchant=merchant)
        )

        if not filtered:
            return MerchantSummary(
                name=merchant.upper(),
                total=Decimal("0"),
                count=0,
                average=Decimal("0"),
                date_range=(date.today(), date.today()),
                transactions=[],
                by_location={},
            )

        total = sum(t.amount for t in filtered)
        count = len(filtered)
        average = total / count if count else Decimal("0")

        dates = [t.transaction_date for t in filtered]
        date_range = (min(dates), max(dates))

        by_location: dict[str, tuple[Decimal, int]] = {}
        for txn in filtered:
            _, location = extract_merchant_info(txn.description)
            loc_key = location or "Unknown"
            current = by_location.get(loc_key, (Decimal("0"), 0))
            by_location[loc_key] = (current[0] + txn.amount, current[1] + 1)

        return MerchantSummary(
            name=merchant.upper(),
            total=total,
            count=count,
            average=average,
            date_range=date_range,
            transactions=filtered,
            by_location=by_location,
        )

    def category_summary(
        self, transactions: list[Transaction]
    ) -> dict[str, tuple[Decimal, int]]:
        result: dict[str, tuple[Decimal, int]] = {}
        for txn in transactions:
            current = result.get(txn.category, (Decimal("0"), 0))
            result[txn.category] = (current[0] + txn.amount, current[1] + 1)
        return result

    def format_text(self, summary: MerchantSummary) -> str:
        lines = []
        lines.append(f"Merchant Report: {summary.name}")
        lines.append("═" * 60)
        lines.append("")

        lines.append("Summary")
        # Calculate purchases vs refunds breakdown
        purchases = sum(t.amount for t in summary.transactions if t.amount > 0)
        refunds = sum(t.amount for t in summary.transactions if t.amount < 0)
        if refunds < 0:
            lines.append(f"  Purchases:         ${purchases:,.2f}")
            lines.append(f"  Refunds:           ${refunds:,.2f}")
            lines.append(f"  Net Total:         ${summary.total:,.2f}")
        else:
            lines.append(f"  Total:             ${summary.total:,.2f}")
        lines.append(f"  Transaction count: {summary.count}")
        lines.append(f"  Average:           ${summary.average:,.2f}")
        if summary.count > 0:
            lines.append(
                f"  Date range:        {summary.date_range[0]} to {summary.date_range[1]}"
            )
        lines.append("")

        if summary.transactions:
            lines.append("Transactions")
            for txn in summary.transactions:
                amount_str = f"${txn.amount:,.2f}"
                if txn.amount < 0:
                    amount_str += "  (refund)"
                lines.append(
                    f"  {txn.transaction_date}  {txn.description:<40} {amount_str:>12}"
                )
            lines.append("")

        if summary.by_location:
            lines.append("By Location")
            sorted_locs = sorted(
                summary.by_location.items(),
                key=lambda x: x[1][0],
                reverse=True,
            )
            for loc, (total, count) in sorted_locs:
                lines.append(f"  {loc:<25} ${total:>10,.2f}  ({count} transactions)")

        return "\n".join(lines)

    def format_json(self, summary: MerchantSummary) -> str:
        data = {
            "merchant": summary.name,
            "total": float(summary.total),
            "count": summary.count,
            "average": float(summary.average),
            "date_range": {
                "from": summary.date_range[0].isoformat(),
                "to": summary.date_range[1].isoformat(),
            },
            "transactions": [t.to_dict() for t in summary.transactions],
            "by_location": {
                loc: {"total": float(total), "count": count}
                for loc, (total, count) in summary.by_location.items()
            },
        }
        return json.dumps(data, indent=2)

    def format_csv(self, summary: MerchantSummary) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Posting Date", "Description", "Amount", "Category", "Reference"
        ])
        for txn in summary.transactions:
            writer.writerow([
                txn.transaction_date.isoformat(),
                txn.posting_date.isoformat(),
                txn.description,
                float(txn.amount),
                txn.category,
                txn.reference_number or "",
            ])
        return output.getvalue()

    def format_filtered_text(self, transactions: list[Transaction], title: str = "Filtered Transactions") -> str:
        lines = []
        lines.append(title)
        lines.append("═" * 60)
        lines.append("")

        total = sum(t.amount for t in transactions)
        lines.append("Summary")
        lines.append(f"  Total:             ${total:,.2f}")
        lines.append(f"  Transaction count: {len(transactions)}")
        if transactions:
            dates = [t.transaction_date for t in transactions]
            lines.append(f"  Date range:        {min(dates)} to {max(dates)}")
        lines.append("")

        if transactions:
            lines.append("Transactions")
            for txn in transactions:
                amount_str = f"${txn.amount:,.2f}"
                lines.append(
                    f"  {txn.transaction_date}  {txn.description:<40} {amount_str:>12}"
                )

        return "\n".join(lines)
