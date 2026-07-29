from pathlib import Path

import pytest

from airx.model import ParseError
from airx.parser import parse


def test_parses_frontmatter_and_body(tmp_path: Path) -> None:
    f = tmp_path / "SKILL.md"
    f.write_text(
        "---\nname: demo\ndescription: Demonstrates parsing.\n---\n\n# Demo\n\nBody text.\n",
        encoding="utf-8",
    )
    doc = parse(f)
    assert doc.frontmatter == {"name": "demo", "description": "Demonstrates parsing."}
    assert "Body text." in doc.body
    assert doc.line_count == len(doc.raw_text.splitlines())


def test_handles_bom_and_crlf(tmp_path: Path) -> None:
    f = tmp_path / "SKILL.md"
    raw = "\ufeff---\r\nname: demo\r\n---\r\n\r\nBody\r\n"
    f.write_bytes(raw.encode("utf-8"))
    doc = parse(f)
    assert doc.frontmatter["name"] == "demo"


def test_missing_frontmatter_returns_empty_dict(tmp_path: Path) -> None:
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Just a heading\n\nNo frontmatter here.\n", encoding="utf-8")
    doc = parse(f)
    assert doc.frontmatter == {}
    assert doc.body == doc.raw_text


def test_invalid_yaml_raises_parse_error(tmp_path: Path) -> None:
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: [unterminated\n---\nBody\n", encoding="utf-8")
    with pytest.raises(ParseError):
        parse(f)


def test_non_mapping_frontmatter_treated_as_empty(tmp_path: Path) -> None:
    f = tmp_path / "SKILL.md"
    f.write_text("---\n- a\n- b\n---\nBody\n", encoding="utf-8")
    doc = parse(f)
    assert doc.frontmatter == {}
