"""CLI for bank statement anonymizer."""

import json
import logging
from pathlib import Path

import click

from anonymizer.core.processor import PDFAnonymizer


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Bank Statement Anonymizer - local, privacy-preserving PDF processing."""
    pass


@cli.command()
@click.argument("input_pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Output PDF path (default: anonymized_<filename>.pdf)",
)
@click.option(
    "--inspect",
    is_flag=True,
    help="Also create .json inspection file",
)
@click.option(
    "--names",
    multiple=True,
    help="Names to anonymize (can be used multiple times: --names John --names Smith)",
)
def anonymize(
    input_pdf: Path,
    output: Path | None,
    inspect: bool,
    names: tuple[str],
) -> None:
    """Anonymize a bank statement PDF.

    Removes/replaces sensitive personal and financial information while
    preserving document structure, page layout, and transaction format.

    The original PDF is NEVER modified or uploaded anywhere.
    Processing is entirely local.

    Output:
      - anonymized_<name>.pdf (anonymized statement)
      - anonymized_<name>.json (inspection data, if --inspect)

    Example:
      python -m anonymizer.main anonymize statement.pdf
      python -m anonymizer.main anonymize statement.pdf --names "John Smith" --inspect
      python -m anonymizer.main anonymize statement.pdf --names John --names Smith
    """
    if not output:
        output = input_pdf.parent / f"anonymized_{input_pdf.name}"

    custom_names = list(names) if names else None
    anonymizer = PDFAnonymizer(custom_names=custom_names)

    try:
        result = anonymizer.anonymize(
            input_pdf,
            output,
            create_inspection_file=inspect,
        )

        click.echo(f"\n✓ Anonymized PDF: {output}")
        click.echo(f"  Pages: {result.pages_total}")
        click.echo(f"  Items anonymized: {len(result.detections)}")

        # Summary by type
        by_type = {}
        for det in result.detections:
            by_type.setdefault(det.detection_type, 0)
            by_type[det.detection_type] += 1

        if by_type:
            click.echo(f"\n  Breakdown:")
            for det_type, count in sorted(by_type.items()):
                click.echo(f"    {det_type}: {count}")

        if inspect:
            inspection_path = output.with_suffix(".json")
            click.echo(f"\n✓ Inspection file: {inspection_path}")
            click.echo(f"  (safe for sharing - no sensitive values included)")

        click.echo(f"\n⚠ IMPORTANT: Review the anonymized PDF visually before sharing.")
        click.echo(f"  The structure is preserved for parser development, but")
        click.echo(f"  nothing replaces manual verification of sensitive data removal.")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("input_pdf", type=click.Path(exists=True, path_type=Path))
def inspect(input_pdf: Path) -> None:
    """Inspect a PDF without anonymizing.

    Shows what would be detected/removed and PDF structure information.
    No files are modified or created.

    Example:
      python -m anonymizer.main inspect statement.pdf
    """
    anonymizer = PDFAnonymizer()

    try:
        result = anonymizer.inspect_pdf(input_pdf)

        click.echo(f"\n=== PDF Inspection ===")
        click.echo(f"File: {input_pdf}")
        click.echo(f"Pages: {result.pages_total}")
        click.echo(f"Text blocks extracted: {len(result.text_blocks)}")
        click.echo(f"Sensitive items found: {len(result.detections)}")

        if result.detections:
            click.echo(f"\nDetected items by type:")
            by_type = {}
            for det in result.detections:
                by_type.setdefault(det.detection_type, [])
                by_type[det.detection_type].append(det)

            for det_type in sorted(by_type.keys()):
                dets = by_type[det_type]
                click.echo(f"  {det_type}: {len(dets)}")
                for det in dets[:3]:  # Show first 3
                    click.echo(f"    - Page {det.page_num + 1}: {det.replacement}")
                if len(dets) > 3:
                    click.echo(f"    ... and {len(dets) - 3} more")
        else:
            click.echo(f"\nNo sensitive items detected.")

        click.echo(f"\nTo anonymize: python -m anonymizer.main anonymize {input_pdf.name}")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
