# Bank Statement Parser

Parse bank statement PDFs and export financial data to Google Sheets.

## Features

- **Extensible provider system**: Add support for new banks by creating a provider class
- **AI-assisted provider generation**: Use local LLM (Ollama) to automatically create providers
- **Iterative learning**: Self-correcting loop that learns from validation failures
- **Full data extraction**: Transactions, account summary, rewards, interest rates
- **Google Sheets export**: Single master spreadsheet with deduplication
- **CLI interface**: Parse single files or batch process directories

## Installation

```bash
make install
```

Or manually:
```bash
python -m venv .venv
source .venv/bin/activate
pip install pdfplumber click gspread google-auth requests pytest
```

## Quick Start

```bash
# Parse a statement
make parse PDF="statement.pdf"

# Learn from a new statement format (creates temp provider)
make learn PDF="statement.pdf"

# Test the temp provider
make parse-temp PDF="statement.pdf"

# Commit to production
make commit-provider BANK=chase
```

## Makefile Commands

```bash
make help          # Show all available commands

# Setup
make install       # Create venv and install dependencies
make reinstall     # Force reinstall all dependencies
make clean         # Remove venv and cache files

# Parse & Export
make parse PDF="statement.pdf"                    # Parse to JSON
make export PDF="statement.pdf" CREDS=creds.json  # Export to Sheets
make batch DIR=./statements CREDS=creds.json      # Batch process

# Reports
make report PDF="statement.pdf" MERCHANT=lowes           # Merchant report
make report PDF="statement.pdf" CATEGORY=purchase        # By category
make report PDF="statement.pdf" MIN=100                  # With amount filter

# AI-Assisted Provider Generation
make learn PDF="statement.pdf"           # Learn and create temp provider
make parse-temp PDF="statement.pdf"      # Test temp provider
make commit-provider BANK=bank_name      # Promote to production

# Ollama (Local LLM)
make ollama-start    # Start Ollama and pull model
make ollama-stop     # Stop Ollama
make ollama-status   # Check status

# Testing
make test                            # Run all tests
make test-provider PROVIDER=chase    # Test specific provider

# List providers
make providers
```

## AI-Assisted Provider Generation

The tool can automatically create providers by analyzing PDF statements using a local LLM.

### Prerequisites

Install Ollama and pull the vision model:
```bash
# macOS
brew install ollama
ollama pull qwen2.5vl:3b

# Or use make
make ollama-start
```

### Two-Stage Workflow

1. **Learn**: Analyze PDF and create a temp provider
   ```bash
   make learn PDF="statement.pdf"
   ```

2. **Test**: Verify the temp provider works
   ```bash
   make parse-temp PDF="statement.pdf"
   ```

3. **Commit**: Promote to production
   ```bash
   make commit-provider BANK=chase
   ```

The learning process:
- Detects bank name and patterns
- Extracts transaction format from sample lines
- Iteratively improves regex patterns
- Falls back to heuristics when LLM fails

## Supported Banks

- **Bank of America Credit Card** (`bofa_credit`)
- **Chase** (`chase`)
- **Citi** (`citi`)

## Adding a New Provider

### Option 1: AI-Assisted (Recommended)

```bash
make learn PDF="new_bank_statement.pdf"
make parse-temp PDF="new_bank_statement.pdf"
make commit-provider BANK=new_bank
```

### Option 2: Manual

Create a new file in `src/providers/`:

```python
from src.providers.base import StatementProvider, register_provider
from src.core.models import Statement

class MyBankProvider(StatementProvider):
    name = "My Bank"
    bank_id = "my_bank"

    def can_parse(self, text: str, pages: list[str]) -> float:
        if "MY BANK" in text.upper():
            return 0.9
        return 0.0

    def parse(self, text: str, pages: list[str]) -> Statement:
        # Extract data using regex patterns
        ...

register_provider(MyBankProvider())
```

Then import it in `src/providers/base.py`:
```python
def load_providers() -> None:
    from src.providers import bofa_credit
    from src.providers import my_bank  # Add this
```

## Google Sheets Export

First, set up Google Sheets API:
1. Create a service account in Google Cloud Console
2. Enable the Google Sheets API
3. Download the JSON credentials file
4. Share your target spreadsheet with the service account email

```bash
make export PDF="statement.pdf" CREDS=credentials.json
```

The exporter creates these tabs:
- **Transactions**: All transactions with deduplication
- **Statements**: One row per imported statement
- **Rewards**: Cash back / points tracking
- **Interest Rates**: APR history by statement

## Project Structure

```
src/
├── main.py                 # CLI entry point
├── core/
│   ├── models.py           # Data models (Statement, Transaction)
│   ├── exporter.py         # Google Sheets exporter
│   └── reports.py          # Report generation
├── providers/
│   ├── base.py             # Provider base class and registry
│   ├── bofa_credit.py      # Bank of America
│   ├── chase.py            # Chase
│   └── citi.py             # Citi
├── tools/
│   ├── ai_generator.py     # AI-assisted provider generation
│   ├── iterative_generator.py  # Self-correcting learning loop
│   └── generator.py        # Interactive wizard
└── utils/
    ├── pdf.py              # PDF text extraction
    └── patterns.py         # Common regex patterns
```

## License

MIT
