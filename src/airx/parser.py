"""Markdown + YAML-frontmatter parsing.

Adapted from AgentEval's `agenteval/parser.py` (MIT licensed): tolerant of a
leading UTF-8 BOM and CRLF line endings within the frontmatter delimiters.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from airx.model import ParseError, ParsedDocument

# Matches an opening ---, YAML content, and closing ---, tolerating trailing
# spaces and CRLF line endings.
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)


def parse(path: Path) -> ParsedDocument:
    """Load and structurally split a Markdown file into frontmatter and body."""
    try:
        # utf-8-sig strips a leading BOM if present.
        raw_text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(f"File is not valid UTF-8: {path}") from exc

    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        return ParsedDocument(path=path, frontmatter={}, frontmatter_raw="", body=raw_text, raw_text=raw_text)

    fm_raw = match.group(1)
    try:
        frontmatter = yaml.safe_load(fm_raw)
    except yaml.YAMLError as exc:
        raise ParseError(f"Invalid YAML frontmatter in {path}: {exc}") from exc

    if not isinstance(frontmatter, dict):
        # A scalar/list/None frontmatter body is malformed for our purposes;
        # treat it as empty and let downstream required-field rules report
        # the missing fields, rather than crashing the whole analysis.
        frontmatter = {}

    body = raw_text[match.end():]
    return ParsedDocument(path=path, frontmatter=frontmatter, frontmatter_raw=fm_raw, body=body, raw_text=raw_text)
