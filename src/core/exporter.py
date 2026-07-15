import hashlib
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from src.core.models import Statement


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleSheetsExporter:
    def __init__(self, credentials_path: Path) -> None:
        creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
        self.client = gspread.authorize(creds)

    def export(self, statement: Statement, spreadsheet_name: str) -> str:
        """Export statement to Google Sheets. Returns spreadsheet URL."""
        try:
            spreadsheet = self.client.open(spreadsheet_name)
        except gspread.SpreadsheetNotFound:
            spreadsheet = self.client.create(spreadsheet_name)

        self._ensure_worksheets(spreadsheet)
        self._export_statement_row(spreadsheet, statement)
        self._export_transactions(spreadsheet, statement)
        self._export_rewards(spreadsheet, statement)
        self._export_interest_rates(spreadsheet, statement)

        return spreadsheet.url

    def _ensure_worksheets(self, spreadsheet: gspread.Spreadsheet) -> None:
        existing = {ws.title for ws in spreadsheet.worksheets()}

        if "Transactions" not in existing:
            ws = spreadsheet.add_worksheet("Transactions", rows=1000, cols=10)
            ws.update("A1:J1", [[
                "Date", "Posting Date", "Description", "Category", "Amount",
                "Reference", "Bank", "Account", "Statement Period", "Import Date"
            ]])
            ws.format("A1:J1", {"textFormat": {"bold": True}})

        if "Statements" not in existing:
            ws = spreadsheet.add_worksheet("Statements", rows=100, cols=15)
            ws.update("A1:O1", [[
                "Import Date", "Bank", "Account", "Holder", "Period Start", "Period End",
                "Prev Balance", "Payments", "Purchases", "Fees", "Interest",
                "New Balance", "Due Date", "Min Payment", "Credit Limit"
            ]])
            ws.format("A1:O1", {"textFormat": {"bold": True}})

        if "Rewards" not in existing:
            ws = spreadsheet.add_worksheet("Rewards", rows=100, cols=8)
            ws.update("A1:H1", [[
                "Statement Period", "Bank", "Account", "Type",
                "Base Earned", "Bonus Earned", "Relationship Bonus", "Total Available"
            ]])
            ws.format("A1:H1", {"textFormat": {"bold": True}})

        if "Interest Rates" not in existing:
            ws = spreadsheet.add_worksheet("Interest Rates", rows=100, cols=7)
            ws.update("A1:G1", [[
                "Statement Period", "Bank", "Account", "Balance Type",
                "APR", "Variable", "Import Date"
            ]])
            ws.format("A1:G1", {"textFormat": {"bold": True}})

        if "Sheet1" in existing:
            try:
                spreadsheet.del_worksheet(spreadsheet.worksheet("Sheet1"))
            except gspread.exceptions.APIError:
                pass

    def _export_statement_row(self, spreadsheet: gspread.Spreadsheet, statement: Statement) -> None:
        ws = spreadsheet.worksheet("Statements")
        period_key = f"{statement.account_number}|{statement.statement_period[0]}|{statement.statement_period[1]}"

        existing = ws.get_all_values()
        for row in existing[1:]:
            if len(row) >= 6:
                row_key = f"{row[2]}|{row[4]}|{row[5]}"
                if row_key == period_key:
                    return

        row = [
            datetime.now().isoformat(),
            statement.bank_name,
            statement.account_number,
            statement.holder_name,
            statement.statement_period[0].isoformat(),
            statement.statement_period[1].isoformat(),
            float(statement.summary.previous_balance),
            float(statement.summary.payments_credits),
            float(statement.summary.purchases_adjustments),
            float(statement.summary.fees),
            float(statement.summary.interest),
            float(statement.summary.new_balance),
            statement.payment_due_date.isoformat() if statement.payment_due_date else "",
            float(statement.minimum_payment) if statement.minimum_payment else "",
            float(statement.summary.credit_limit) if statement.summary.credit_limit else "",
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")

    def _export_transactions(self, spreadsheet: gspread.Spreadsheet, statement: Statement) -> None:
        ws = spreadsheet.worksheet("Transactions")
        existing = ws.get_all_values()
        existing_hashes = set()

        for row in existing[1:]:
            if len(row) >= 5:
                h = self._transaction_hash(row[0], row[1], row[2], row[4], row[7])
                existing_hashes.add(h)

        period_str = f"{statement.statement_period[0]} to {statement.statement_period[1]}"
        import_date = datetime.now().isoformat()
        new_rows = []

        for txn in statement.transactions:
            h = self._transaction_hash(
                txn.transaction_date.isoformat(),
                txn.posting_date.isoformat(),
                txn.description,
                str(float(txn.amount)),
                statement.account_number,
            )
            if h in existing_hashes:
                continue

            new_rows.append([
                txn.transaction_date.isoformat(),
                txn.posting_date.isoformat(),
                txn.description,
                txn.category,
                float(txn.amount),
                txn.reference_number or "",
                statement.bank_name,
                statement.account_number,
                period_str,
                import_date,
            ])

        if new_rows:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    def _export_rewards(self, spreadsheet: gspread.Spreadsheet, statement: Statement) -> None:
        if not statement.rewards:
            return

        ws = spreadsheet.worksheet("Rewards")
        period_str = f"{statement.statement_period[0]} to {statement.statement_period[1]}"

        existing = ws.get_all_values()
        for row in existing[1:]:
            if len(row) >= 3 and row[0] == period_str and row[2] == statement.account_number:
                return

        row = [
            period_str,
            statement.bank_name,
            statement.account_number,
            statement.rewards.reward_type,
            float(statement.rewards.base_earned),
            float(statement.rewards.bonus_earned),
            float(statement.rewards.relationship_bonus),
            float(statement.rewards.total_available),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")

    def _export_interest_rates(self, spreadsheet: gspread.Spreadsheet, statement: Statement) -> None:
        if not statement.interest_rates:
            return

        ws = spreadsheet.worksheet("Interest Rates")
        period_str = f"{statement.statement_period[0]} to {statement.statement_period[1]}"
        import_date = datetime.now().isoformat()

        existing = ws.get_all_values()
        existing_keys = set()
        for row in existing[1:]:
            if len(row) >= 4:
                existing_keys.add(f"{row[0]}|{row[2]}|{row[3]}")

        new_rows = []
        for rate in statement.interest_rates:
            key = f"{period_str}|{statement.account_number}|{rate.balance_type}"
            if key in existing_keys:
                continue

            new_rows.append([
                period_str,
                statement.bank_name,
                statement.account_number,
                rate.balance_type,
                float(rate.apr),
                "Yes" if rate.is_variable else "No",
                import_date,
            ])

        if new_rows:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    def _transaction_hash(self, date: str, post_date: str, desc: str, amount: str, account: str) -> str:
        key = f"{date}|{post_date}|{desc}|{amount}|{account}"
        return hashlib.md5(key.encode()).hexdigest()
