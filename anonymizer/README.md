# Bank Statement Anonymizer

A local, privacy-preserving PDF anonymizer for bank statements. Detects and replaces sensitive personal and financial information while preserving document structure.

## Features

- **Local-only processing** — PDFs never leave your machine
- **Structure preservation** — Keeps page layout, formatting, and table structure intact
- **Semantic replacement** — Replaces sensitive values with labeled placeholders (e.g., `[NAME]`, `[ACCOUNT]`)
- **Safe inspection** — Produces JSON metadata files without original sensitive values
- **Modular detection** — Pluggable detectors for extensibility

## What Gets Anonymized

| Type | Detections | Replacement |
|------|-----------|-------------|
| Names | Personal names (common first/last pairs + custom names) | `[NAME]` |
| Amounts | Monetary values, balances | `$0.00` |
| Addresses | Street addresses, city/state/ZIP | `[ADDRESS]`, `[CITY, STATE ZIP]` |
| Accounts | Account numbers, routing numbers | `[ACCOUNT]`, `[ROUTING]` |
| Account Endings | Account Ending XXXX, XXXXXXXX1234 patterns | `[ACCOUNT]` |
| Identifiers | SSN, EIN, check numbers, tax IDs | `[SSN]`, `[ID]`, `[CHECK]` |
| Dates | *Usually preserved* — part of transaction structure | (unchanged) |
| Column headers | *Preserved* — "Date", "Amount", "Balance" | (unchanged) |
| Merchant names | *Preserved* by default — use for parser development | (unchanged) |

## Installation

```bash
# Install dependencies
pip install PyMuPDF>=1.26 click>=8.0

# Or use the existing project environment
make install  # if Makefile has been updated with anonymizer deps
```

## Usage

### Anonymize a PDF

```bash
# Basic anonymization
python -m anonymizer.main anonymize statement.pdf

# With custom output path
python -m anonymizer.main anonymize statement.pdf --output safe_statement.pdf

# Also create inspection file
python -m anonymizer.main anonymize statement.pdf --inspect

# Anonymize specific names (in addition to common names)
python -m anonymizer.main anonymize statement.pdf --names "John Smith" --names "Jane Doe"

# Or use multiple --names flags
python -m anonymizer.main anonymize statement.pdf --names John --names Smith
```

### Inspect Without Anonymizing

```bash
# See what would be detected
python -m anonymizer.main inspect statement.pdf
```

### Output

- **Anonymized PDF**: `anonymized_<name>.pdf`
  - Original layout preserved
  - Sensitive values replaced with bracketed labels
  - Ready for use in parser development
  
- **Inspection file** (optional): `anonymized_<name>.json`
  - Detection details (type, page, bbox, replacement, confidence)
  - Text block positions
  - PDF metadata
  - **Safe to share** — contains no original sensitive values

## Architecture

```
anonymizer/
├── core/
│   ├── models.py          # Detection and result data classes
│   └── processor.py       # PDF processing logic (PyMuPDF + coordination)
├── detectors/
│   ├── base.py            # Detector interface
│   ├── amounts.py         # Monetary values
│   ├── names.py           # Personal names (common + custom)
│   ├── addresses.py       # Addresses
│   ├── account_numbers.py # Account/routing/check numbers
│   ├── account_endings.py # Account ending patterns (Ending XXXX, XXXXXXXX1234)
│   ├── identifiers.py     # SSN, EIN, government IDs
│   └── dates.py           # Date detection (for preservation)
├── main.py                # CLI interface
└── tests/
    └── test_detectors.py  # Unit tests
```

## Detection Strategy

Detectors use a **multi-pass, high-to-low-confidence** approach:

1. **IdentifierDetector** — High confidence: SSN format, EIN, routing numbers with labels
2. **AccountNumberDetector** — High confidence: Account numbers with explicit labels
3. **NameDetector** — Medium confidence: Common first/last name patterns
4. **AddressDetector** — Medium confidence: Street address, city/state/ZIP patterns
5. **AmountDetector** — Lower confidence: Monetary values (guards against false positives)

Overlapping detections are **deduplicated**, keeping the highest-confidence match.

## Design Principles

### Structure Preservation
The goal is to preserve structure for **parser development**, not just hide information. Column headers, dates, transaction descriptions, and formatting remain intact. This allows deterministic bank-statement parsers to be built and tested against anonymized but structurally-sound examples.

### No Over-Anonymization
Merchant names, dates, column headers, and amounts that appear in context (like labels) are preserved unless they match high-confidence patterns. A row like `Wells Fargo $25.00 Debit 01/15/2026` becomes `Wells Fargo $0.00 Debit 01/15/2026` — recognizable as a transaction.

### Privacy-First Logging
The original `Detection` object never stores original sensitive text after creation. Detection reason strings use generic descriptions like "Monetary amount detected" instead of "Found $1,234.56".

### Local Processing
All processing happens with PyMuPDF (fitz) and standard Python libraries. No network calls, no external APIs, no uploaded files.

## Testing

Run unit tests:

```bash
pytest anonymizer/tests/
```

Tests cover detector behavior on common patterns:
- Dollar amounts with various formats
- Common names (John, Mary, Smith, etc.)
- Address formats (street, city/state/ZIP)
- Account numbers with labels
- SSN, EIN, check numbers
- Date preservation
- False-positive prevention

## Limitations

- **Text-based PDFs only** — scanned/image PDFs require OCR (not currently implemented)
- **English-focused patterns** — detectors use English-language heuristics
- **Conservative on low-confidence items** — may miss unusual formats
- **No entity recognition** — detects patterns, not semantic context beyond immediate label proximity
- **Manual verification required** — always review anonymized PDFs visually before sharing

## Integration Notes

This tool is **independent** and can be run standalone:

```bash
python -m anonymizer.main anonymize <path>
```

For future integration with the parser (`src/main.py`), the `PDFAnonymizer` class can be imported:

```python
from anonymizer.core.processor import PDFAnonymizer

anonymizer = PDFAnonymizer()
result = anonymizer.anonymize(input_path, output_path)
```

The `AnonymizationResult` contains detections and text blocks useful for parser validation.

## Contributing

New detectors should:

1. Inherit from `Detector` (base.py)
2. Implement `detect(text_blocks)` → `list[Detection]`
3. Implement `get_replacement(text, detection_type)` → `str`
4. Add unit tests in `test_detectors.py`
5. Register in `PDFAnonymizer.__init__()` (processor.py)

Example detector template:

```python
from .base import Detector

class MyDetector(Detector):
    def detect(self, text_blocks):
        detections = []
        for block in text_blocks:
            if self._matches_pattern(block.text):
                detections.append(
                    self._log_detection(
                        text=block.text,
                        detection_type="mytype",
                        bbox=block.bbox,
                        page_num=block.page_num,
                        replacement="[REPLACEMENT]",
                        confidence=0.8,
                        reason="Pattern matched",
                    )
                )
        return detections
    
    def get_replacement(self, text, detection_type):
        return "[REPLACEMENT]"
```

## Warnings

⚠️ **Always verify anonymized PDFs visually** before sharing. This tool uses pattern matching, not perfect identification. Sensitive data may remain or may be incorrectly anonymized.

⚠️ **The inspection JSON is safe to share** (no original sensitive values), but even anonymized PDFs should be reviewed by a human before distribution.

## License

Same as parent project.
