"""Command-line entry point."""
from __future__ import annotations

import sys
from pathlib import Path

import click

import airx.rules  # noqa: F401  (registers built-in rules on import)
from airx import fs
from airx.discovery import build_index
from airx.report import to_json, to_terminal
from airx.scoring import score


@click.group()
def main() -> None:
    """AI Readiness Analyzer — deterministic AI-readiness scoring."""


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["terminal", "json"]), default="terminal")
@click.option("--fail-on", type=click.Choice(["error", "never"]), default="error")
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
def analyze(path: Path, fmt: str, fail_on: str, output: Path | None) -> None:
    """Analyze PATH and print an AI-readiness report."""
    tree = fs.scan(path)
    index = build_index(tree)
    card = score(index)

    rendered = to_json(index, card) if fmt == "json" else to_terminal(index, card)

    if output is not None:
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        click.echo(rendered)

    if fail_on == "error" and card.has_error_finding:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
