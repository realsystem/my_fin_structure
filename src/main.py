import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import click

from src.core.exporter import GoogleSheetsExporter
from src.core.models import Statement, Transaction
from src.core.reports import ReportGenerator, TransactionFilter
from src.providers.base import load_providers, registry
from src.utils.pdf import extract_text


@click.group()
def cli() -> None:
    """Bank Statement Parser - Extract financial data from PDF statements."""
    load_providers()


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output JSON file")
def parse(pdf_path: Path, output: Path | None) -> None:
    """Parse a bank statement PDF and output extracted data."""
    click.echo(f"Parsing {pdf_path}...")

    text, pages = extract_text(pdf_path)
    provider = registry.find_provider(text, pages)

    if provider is None:
        click.echo("Error: No provider found that can parse this document.", err=True)
        raise SystemExit(1)

    click.echo(f"Using provider: {provider.bank_id} ({provider.name})")
    statement = provider.parse(text, pages)

    data = statement.to_dict()
    json_output = json.dumps(data, indent=2, default=str)

    if output:
        output.write_text(json_output)
        click.echo(f"Written to {output}")
    else:
        click.echo(json_output)


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--credentials", "-c",
    type=click.Path(exists=True, path_type=Path),
    envvar="GOOGLE_CREDENTIALS",
    required=True,
    help="Google service account JSON file",
)
@click.option(
    "--spreadsheet", "-s",
    default="Bank Statements",
    help="Spreadsheet name (default: 'Bank Statements')",
)
def export(pdf_path: Path, credentials: Path, spreadsheet: str) -> None:
    """Parse a bank statement and export to Google Sheets."""
    click.echo(f"Parsing {pdf_path}...")

    text, pages = extract_text(pdf_path)
    provider = registry.find_provider(text, pages)

    if provider is None:
        click.echo("Error: No provider found that can parse this document.", err=True)
        raise SystemExit(1)

    click.echo(f"Detected: {provider.name}")
    statement = provider.parse(text, pages)

    click.echo(f"Exporting to Google Sheets '{spreadsheet}'...")
    exporter = GoogleSheetsExporter(credentials)
    url = exporter.export(statement, spreadsheet)

    click.echo(f"Exported {len(statement.transactions)} transactions")
    click.echo(f"Spreadsheet: {url}")


@cli.command()
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--credentials", "-c",
    type=click.Path(exists=True, path_type=Path),
    envvar="GOOGLE_CREDENTIALS",
    required=True,
    help="Google service account JSON file",
)
@click.option(
    "--spreadsheet", "-s",
    default="Bank Statements",
    help="Spreadsheet name (default: 'Bank Statements')",
)
def batch(directory: Path, credentials: Path, spreadsheet: str) -> None:
    """Process all PDF files in a directory."""
    pdf_files = list(directory.glob("*.pdf"))
    if not pdf_files:
        click.echo(f"No PDF files found in {directory}")
        return

    click.echo(f"Found {len(pdf_files)} PDF files")
    exporter = GoogleSheetsExporter(credentials)
    success = 0
    failed = 0

    for pdf_path in pdf_files:
        try:
            text, pages = extract_text(pdf_path)
            provider = registry.find_provider(text, pages)

            if provider is None:
                click.echo(f"  {pdf_path.name}: No matching provider", err=True)
                failed += 1
                continue

            statement = provider.parse(text, pages)
            exporter.export(statement, spreadsheet)
            click.echo(f"  {pdf_path.name}: {len(statement.transactions)} transactions")
            success += 1

        except Exception as e:
            click.echo(f"  {pdf_path.name}: Error - {e}", err=True)
            failed += 1

    click.echo(f"\nProcessed: {success} success, {failed} failed")


@cli.command()
def providers() -> None:
    """List available statement providers."""
    for provider in registry.providers:
        click.echo(f"  {provider.bank_id}: {provider.name}")


def _collect_transactions(source: Path) -> list[Transaction]:
    """Collect transactions from a PDF file or directory of PDFs."""
    transactions: list[Transaction] = []

    if source.is_dir():
        pdf_files = list(source.glob("*.pdf"))
    else:
        pdf_files = [source]

    for pdf_path in pdf_files:
        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)
        if provider:
            statement = provider.parse(text, pages)
            transactions.extend(statement.transactions)

    return transactions


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--merchant", "-m", help="Filter by merchant name (substring match)")
@click.option(
    "--category", "-c",
    type=click.Choice(["payment", "purchase", "interest", "fee"]),
    help="Filter by transaction category",
)
@click.option(
    "--from", "date_from",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Filter transactions from this date",
)
@click.option(
    "--to", "date_to",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Filter transactions until this date",
)
@click.option("--min-amount", type=float, help="Minimum transaction amount")
@click.option("--max-amount", type=float, help="Maximum transaction amount")
@click.option(
    "--format", "output_format",
    type=click.Choice(["text", "json", "csv"]),
    default="text",
    help="Output format (default: text)",
)
def report(
    source: Path,
    merchant: str | None,
    category: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    min_amount: float | None,
    max_amount: float | None,
    output_format: str,
) -> None:
    """Generate a filtered transaction report."""
    transactions = _collect_transactions(source)

    if not transactions:
        click.echo("No transactions found.", err=True)
        raise SystemExit(1)

    generator = ReportGenerator()

    if merchant:
        summary = generator.merchant_summary(transactions, merchant)

        if output_format == "text":
            click.echo(generator.format_text(summary))
        elif output_format == "json":
            click.echo(generator.format_json(summary))
        elif output_format == "csv":
            click.echo(generator.format_csv(summary))
    else:
        filter_obj = TransactionFilter(
            merchant=merchant,
            category=category,
            date_from=date_from.date() if date_from else None,
            date_to=date_to.date() if date_to else None,
            min_amount=Decimal(str(min_amount)) if min_amount else None,
            max_amount=Decimal(str(max_amount)) if max_amount else None,
        )
        filtered = generator.filter(transactions, filter_obj)

        if not filtered:
            click.echo("No transactions match the filter criteria.", err=True)
            raise SystemExit(1)

        if output_format == "text":
            title = "Filtered Transactions"
            if category:
                title = f"{category.title()} Transactions"
            click.echo(generator.format_filtered_text(filtered, title))
        elif output_format == "json":
            data = {
                "count": len(filtered),
                "total": float(sum(t.amount for t in filtered)),
                "transactions": [t.to_dict() for t in filtered],
            }
            click.echo(json.dumps(data, indent=2))
        elif output_format == "csv":
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Date", "Posting Date", "Description", "Amount", "Category", "Reference"])
            for txn in filtered:
                writer.writerow([
                    txn.transaction_date.isoformat(),
                    txn.posting_date.isoformat(),
                    txn.description,
                    float(txn.amount),
                    txn.category,
                    txn.reference_number or "",
                ])
            click.echo(output.getvalue())


@cli.command("generate-provider")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Output path for generated provider (default: src/providers/<bank_id>.py)",
)
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Load configuration from JSON file instead of running wizard",
)
@click.option(
    "--save-config",
    type=click.Path(path_type=Path),
    help="Save configuration to JSON file",
)
def generate_provider(
    pdf_path: Path,
    output: Path | None,
    config: Path | None,
    save_config: Path | None,
) -> None:
    """Generate a new provider from a sample PDF statement."""
    from src.tools.generator import ProviderGenerator

    generator = ProviderGenerator(pdf_path)

    if config:
        generator.config = ProviderGenerator.load_config(config)
        click.echo(f"Loaded configuration from {config}")
    else:
        generator.run_wizard(click.echo, click.prompt, click.confirm)

    output_path = output or Path(f"src/providers/{generator.config.bank_id}.py")

    click.echo(f"\n── Generating Provider ──")
    generator.save_provider(output_path)
    click.echo(f"Saved provider to: {output_path}")

    if save_config:
        generator.save_config(save_config)
        click.echo(f"Saved config to: {save_config}")

    click.echo(f"\n── Validation ──")
    click.echo("Testing generated provider...")

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("new_provider", output_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        text, pages = extract_text(pdf_path)
        provider = registry.find_provider(text, pages)

        if provider and provider.bank_id == generator.config.bank_id:
            statement = provider.parse(text, pages)
            click.echo(f"  Account: {statement.account_number}")
            click.echo(f"  Period: {statement.statement_period[0]} to {statement.statement_period[1]}")
            click.echo(f"  Transactions: {len(statement.transactions)}")
            if statement.transactions:
                click.echo(f"  Sample: {statement.transactions[0].description} ${statement.transactions[0].amount}")
            click.echo("\nProvider generated successfully!")
        else:
            click.echo("Warning: Provider was created but didn't match the PDF.", err=True)
            click.echo("You may need to adjust detection patterns.", err=True)

    except Exception as e:
        click.echo(f"Warning: Validation failed: {e}", err=True)
        click.echo("The provider was generated but may need manual adjustments.", err=True)

    click.echo(f"\nTo use: Add 'from src.providers import {generator.config.bank_id}' to src/providers/base.py")


@cli.command("ai-generate")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Output path for generated provider",
)
@click.option(
    "--model", "-m",
    default="qwen2.5vl:3b",
    help="Ollama model to use (default: qwen2.5vl:3b)",
)
@click.option(
    "--save-config",
    type=click.Path(path_type=Path),
    help="Save AI-generated config to JSON file",
)
@click.option(
    "--no-tests",
    is_flag=True,
    help="Skip test generation and validation",
)
@click.option(
    "--no-register",
    is_flag=True,
    help="Don't auto-register provider on success",
)
def ai_generate_provider(
    pdf_path: Path,
    output: Path | None,
    model: str,
    save_config: Path | None,
    no_tests: bool,
    no_register: bool,
) -> None:
    """Generate a provider using AI analysis (requires Ollama)."""
    from src.tools.ai_generator import AIProviderGenerator

    click.echo(f"Analyzing {pdf_path} with {model}...")

    try:
        generator = AIProviderGenerator(model=model)
        config = generator.analyze_pdf(pdf_path)

        click.echo(f"\nDetected: {config.get('bank_name', 'Unknown')}")
        click.echo(f"Account regex: {config.get('account_number_regex', 'N/A')}")
        click.echo(f"Transaction columns: {config.get('transaction_columns', [])}")

        if save_config:
            Path(save_config).write_text(json.dumps(config, indent=2))
            click.echo(f"Saved config to: {save_config}")

        output_path = output or Path(f"src/providers/{config['bank_id']}.py")
        code = generator.generate_provider_code(config)
        output_path.write_text(code)
        click.echo(f"Saved provider to: {output_path}")

        click.echo(f"\n── Validation ──")
        click.echo("Validating generated provider...")

        success, message, stats = generator.validate_provider(output_path, pdf_path)

        if not success:
            click.echo(f"✗ Validation failed: {message}", err=True)
            click.echo("Provider needs manual adjustments.", err=True)
            click.echo(f"\nTo use manually: Add 'from src.providers import {config['bank_id']}' to src/providers/base.py")
            raise SystemExit(1)

        click.echo(f"✓ {message}")
        click.echo(f"  Account: {stats['account_number']}")
        click.echo(f"  Period: {stats['statement_period'][0]} to {stats['statement_period'][1]}")
        click.echo(f"  Transactions: {stats['transaction_count']}")
        click.echo(f"  Payments: ${stats['payments_total']}, Purchases: ${stats['purchases_total']}")

        if not no_tests:
            click.echo(f"\n── Generating Tests ──")
            test_code = generator.generate_tests(config, stats, pdf_path.name)
            test_file = Path("tests/test_providers.py")
            generator.add_tests_to_file(test_code, test_file)
            click.echo(f"Added tests to: {test_file}")

            click.echo(f"\n── Running Tests ──")
            test_success, test_output = generator.run_tests(config["bank_id"])

            if not test_success:
                click.echo("✗ Tests failed:", err=True)
                click.echo(test_output, err=True)
                click.echo(f"\nProvider saved but tests failed. Fix and run: make test-provider PROVIDER={config['bank_id']}")
                raise SystemExit(1)

            # Show test summary
            passed = test_output.count(" PASSED")
            click.echo(f"✓ {passed} tests passed")

        if not no_register:
            click.echo(f"\n── Registering Provider ──")
            if generator.register_provider(config["bank_id"], Path("src")):
                click.echo(f"✓ Provider '{config['bank_id']}' registered in base.py")
            else:
                click.echo(f"⚠ Could not auto-register. Add manually:")
                click.echo(f"  from src.providers import {config['bank_id']}")

        click.echo(f"\n✓ Provider '{config['bank_name']}' created successfully!")

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.command("learn")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--model", "-m",
    default="qwen2.5vl:3b",
    help="Ollama model to use (default: qwen2.5vl:3b)",
)
@click.option(
    "--max-iterations", "-n",
    default=15,
    help="Maximum iterations to try (default: 15)",
)
@click.option(
    "--state-file", "-s",
    type=click.Path(path_type=Path),
    help="State file to resume from or save to",
)
@click.option(
    "--temp/--no-temp",
    default=True,
    help="Create temp provider for testing (default: --temp)",
)
def learn_provider(
    pdf_path: Path,
    model: str,
    max_iterations: int,
    state_file: Path | None,
    temp: bool,
) -> None:
    """Iteratively learn to parse a statement using local LLM.

    Creates a temporary provider for testing. Use 'commit-provider' to
    promote the temp provider to production after verification.

    Example:
        make learn PDF=statement.pdf
        make parse-temp PDF=statement.pdf   # test the temp provider
        make commit-provider BANK=chase     # promote to production
    """
    from src.tools.iterative_generator import IterativeGenerator
    from src.tools.ai_generator import AIProviderGenerator

    mode_str = "temp" if temp else "production"
    click.echo(f"Learning to parse {pdf_path} with {model} ({mode_str} mode)...")
    click.echo(f"Max iterations: {max_iterations}")

    state_path = state_file or Path(f".{pdf_path.stem}_state.json")

    def log(msg: str) -> None:
        click.echo(msg)

    try:
        generator = IterativeGenerator(
            model=model,
            max_iterations=max_iterations,
            log_fn=log,
            temp_mode=temp,
        )

        success, state, provider_path = generator.generate(pdf_path, state_path)

        suffix = "_temp" if temp else ""
        bank_id_display = f"{state.bank_id}{suffix}"

        if not success:
            click.echo(f"\n── Learning incomplete ──")
            click.echo(f"State saved to: {state_path}")
            click.echo(f"Provider saved to: {provider_path}")
            click.echo(f"\nRemaining issues: {', '.join(state.issues)}")
            click.echo(f"\nTo continue learning: make learn PDF={pdf_path}")
            click.echo(f"To edit manually: edit {provider_path}")
            raise SystemExit(1)

        click.echo(f"\n── Learning complete ──")
        click.echo(f"  Bank: {state.bank_name}")
        click.echo(f"  Account: {state.account_number_found or 'n/a'}")
        period_start, period_end = state.statement_period_found
        if period_start and period_end:
            click.echo(f"  Period: {period_start} to {period_end}")
        else:
            click.echo(f"  Period: n/a")
        click.echo(f"  Transactions: {state.transactions_found}")

        if temp:
            click.echo(f"\n── Temp Provider Created ──")
            click.echo(f"  Provider: {provider_path}")
            click.echo(f"\nNext steps:")
            click.echo(f'  1. Test: make parse-temp PDF="{pdf_path}"')
            click.echo(f"  2. Commit: make commit-provider BANK={state.bank_id}")
        else:
            # Full registration flow for non-temp mode
            click.echo(f"\n── Generating Tests ──")
            ai_gen = AIProviderGenerator(model=model)
            stats = {
                "account_number": state.account_number_found,
                "statement_period": state.statement_period_found,
                "transaction_count": state.transactions_found,
                "payments_total": "0",
                "purchases_total": "0",
            }

            # Get actual totals from parsed statement
            text, pages = extract_text(pdf_path)
            provider = registry.find_provider(text, pages)
            if provider:
                statement = provider.parse(text, pages)
                payments = sum(t.amount for t in statement.transactions if t.category == "payment")
                purchases = sum(t.amount for t in statement.transactions if t.category == "purchase")
                stats["payments_total"] = str(payments)
                stats["purchases_total"] = str(purchases)

            test_code = ai_gen.generate_tests(state.to_config(), stats, pdf_path.name)
            test_file = Path("tests/test_providers.py")
            ai_gen.add_tests_to_file(test_code, test_file)
            click.echo(f"Added tests to: {test_file}")

            click.echo(f"\n── Running Tests ──")
            test_success, test_output = ai_gen.run_tests(state.bank_id)
            if test_success:
                passed = test_output.count(" PASSED")
                click.echo(f"✓ {passed} tests passed")
            else:
                click.echo(f"⚠ Some tests failed (provider still usable)")

            click.echo(f"\n── Registering Provider ──")
            if ai_gen.register_provider(state.bank_id, Path("src")):
                click.echo(f"✓ Provider '{state.bank_id}' registered")
            else:
                click.echo(f"Add to base.py: from src.providers import {state.bank_id}")

        # Cleanup state file on success
        if state_path.exists():
            state_path.unlink()
            click.echo(f"Cleaned up: {state_path}")

        click.echo(f"\n✓ Provider '{state.bank_name}' ready to use!")

    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.command("parse-temp")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
def parse_temp(pdf_path: Path) -> None:
    """Parse a PDF using the matching temp provider for testing."""
    import importlib.util

    text, pages = extract_text(pdf_path)

    # Find matching temp provider
    temp_providers = list(Path("src/providers").glob("*_temp.py"))
    if not temp_providers:
        click.echo("No temp providers found. Run 'learn' first.", err=True)
        raise SystemExit(1)

    best_provider = None
    best_score = 0.0

    for temp_path in temp_providers:
        try:
            spec = importlib.util.spec_from_file_location("temp_provider", temp_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find the provider class (skip abstract StatementProvider)
                for name in dir(module):
                    obj = getattr(module, name)
                    if (
                        isinstance(obj, type)
                        and hasattr(obj, "can_parse")
                        and name.endswith("Provider")
                        and name != "StatementProvider"
                        and "Temp" in name
                    ):
                        instance = obj()
                        score = instance.can_parse(text, pages)
                        if score > best_score:
                            best_score = score
                            best_provider = instance
        except Exception as e:
            click.echo(f"Warning: Could not load {temp_path}: {e}", err=True)

    if best_provider is None or best_score < 0.5:
        click.echo(f"No temp provider matched (best score: {best_score:.2f})", err=True)
        raise SystemExit(1)

    click.echo(f"Using temp provider: {best_provider.name} (score: {best_score:.2f})")
    statement = best_provider.parse(text, pages)

    click.echo(f"\n── Statement Summary ──")
    click.echo(f"  Account: {statement.account_number or 'n/a'}")
    if statement.statement_period:
        click.echo(f"  Period: {statement.statement_period[0]} to {statement.statement_period[1]}")
    else:
        click.echo(f"  Period: n/a")
    click.echo(f"  Transactions: {len(statement.transactions)}")

    if statement.transactions:
        payments = [t for t in statement.transactions if t.category == "payment"]
        purchases = [t for t in statement.transactions if t.category == "purchase"]
        click.echo(f"  Payments: {len(payments)} (${sum(t.amount for t in payments)})")
        click.echo(f"  Purchases: {len(purchases)} (${sum(t.amount for t in purchases)})")

        click.echo(f"\n── Transactions ──")
        for t in statement.transactions:
            click.echo(f"  {t.transaction_date} | {t.description[:40]:<40} | ${t.amount:>10} | {t.category}")

    click.echo(f"\nTo commit: make commit-provider BANK={best_provider.bank_id.replace('_temp', '')}")


@cli.command("commit-provider")
@click.argument("bank_id")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing provider without confirmation")
def commit_provider(bank_id: str, force: bool) -> None:
    """Promote a temp provider to production.

    Replaces the existing provider (if any) with the temp version and
    registers it in base.py.
    """
    from src.tools.ai_generator import AIProviderGenerator

    temp_path = Path(f"src/providers/{bank_id}_temp.py")
    prod_path = Path(f"src/providers/{bank_id}.py")

    if not temp_path.exists():
        click.echo(f"Temp provider not found: {temp_path}", err=True)
        click.echo(f"Run 'learn' first to create a temp provider.", err=True)
        raise SystemExit(1)

    if prod_path.exists() and not force:
        if not click.confirm(f"Replace existing provider {prod_path}?"):
            click.echo("Aborted.")
            raise SystemExit(0)

    # Read temp provider and update class name / bank_id
    temp_code = temp_path.read_text()

    # Replace _temp suffix in class name, bank_id, and register call
    import re
    prod_code = re.sub(
        r"class (\w+)TempProvider\(",
        lambda m: f"class {m.group(1)}Provider(",
        temp_code,
    )
    prod_code = re.sub(
        rf'bank_id = "{bank_id}_temp"',
        f'bank_id = "{bank_id}"',
        prod_code,
    )
    prod_code = re.sub(
        r"register_provider\((\w+)TempProvider\(\)\)",
        lambda m: f"register_provider({m.group(1)}Provider())",
        prod_code,
    )

    prod_path.write_text(prod_code)
    click.echo(f"✓ Created: {prod_path}")

    # Remove temp provider
    temp_path.unlink()
    click.echo(f"✓ Removed: {temp_path}")

    # Register in base.py
    ai_gen = AIProviderGenerator()
    if ai_gen.register_provider(bank_id, Path("src")):
        click.echo(f"✓ Registered '{bank_id}' in base.py")
    else:
        click.echo(f"⚠ Could not auto-register. Add manually:")
        click.echo(f"  from src.providers import {bank_id}")

    click.echo(f"\n✓ Provider '{bank_id}' committed to production!")


if __name__ == "__main__":
    cli()
