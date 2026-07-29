"""Unit tests for the v0.2.0 foundation-pillar additions (plan-v2-fable.md §4.1):
foundation.sections.coverage, foundation.imports.resolve, foundation.entrypoint.parses.
"""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import Platform, Severity
import airx.rules.foundation as foundation
from airx.rules.registry import get_rule


def _index(root: Path):
    return build_index(fs.scan(root))


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


# --- foundation.sections.coverage --------------------------------------------

def test_sections_coverage_all_five_signals_satisfied(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": (
            "# Overview\n\nA web app.\n\n"
            "# Tech Stack\n\nPython.\n\n"
            "# Guidelines\n\nBe careful.\n\n"
            "# Project Structure\n\nsrc/ holds it.\n\n"
            "# Commands\n\npytest\n"
        ),
    })
    sat, diags = foundation.check_sections_coverage(_index(root))
    assert sat == 1.0
    assert diags == []


def test_sections_coverage_partial_lists_missing_sections(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": "# Overview\n\nAn intro paragraph.\n",
    })
    sat, diags = foundation.check_sections_coverage(_index(root))
    assert sat == 0.2  # k=1 of 5
    assert len(diags) == 1
    assert diags[0].severity == Severity.INFO
    for missing in ("techstack", "guidelines", "structure", "resources"):
        assert missing in diags[0].message
    assert "overview" not in diags[0].message.split("missing:")[1]


def test_sections_coverage_keyword_in_first_200_body_chars_counts(tmp_path):
    # No headings at all: signals may still count from the body's first 200 chars.
    root = _repo(tmp_path, {
        "CLAUDE.md": "This project is about billing. Tech stack: Python.\n",
    })
    sat, diags = foundation.check_sections_coverage(_index(root))
    # overview ("about") + techstack ("stack") = 2 of 5.
    assert sat == 0.4
    assert len(diags) == 1


def test_sections_coverage_not_applicable_without_entrypoint(tmp_path):
    root = _repo(tmp_path, {"README.md": "# Hello\n"})
    assert foundation.check_sections_coverage(_index(root)) is None


# --- foundation.imports.resolve ----------------------------------------------

def test_imports_resolve_all_targets_exist(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": "Read @AGENTS.md and @docs/setup.md before coding.\n",
        "AGENTS.md": "# Agents\n",
        "docs/setup.md": "# Setup\n",
    })
    sat, diags = foundation.check_imports_resolve(_index(root))
    assert sat == 1.0
    assert diags == []


def test_imports_resolve_missing_target_is_error(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": "See @AGENTS.md and @docs/missing.md\n",
        "AGENTS.md": "# Agents\n",
    })
    sat, diags = foundation.check_imports_resolve(_index(root))
    assert sat == 0.5  # one of two imports resolves
    assert len(diags) == 1
    rel_path, diag = diags[0]
    assert rel_path == PurePosixPath("CLAUDE.md")
    assert diag.severity == Severity.ERROR
    assert "docs/missing.md" in diag.message
    assert "does not exist" in diag.message


def test_imports_resolve_flags_target_escaping_repo_root(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": "Load @src/../../secret.txt\n",
        "src/keep.py": "x = 1\n",
    })
    (tmp_path / "secret.txt").write_text("outside\n", encoding="utf-8")
    sat, diags = foundation.check_imports_resolve(_index(root))
    assert sat == 0.0
    assert len(diags) == 1
    assert "escapes the repository root" in diags[0][1].message


def test_imports_resolve_not_applicable_without_imports(tmp_path):
    root = _repo(tmp_path, {"CLAUDE.md": "# Overview\n\nNo imports here.\n"})
    assert foundation.check_imports_resolve(_index(root)) is None


def test_imports_resolve_not_applicable_without_claude_md(tmp_path):
    root = _repo(tmp_path, {".github/copilot-instructions.md": "See @AGENTS.md\n"})
    assert foundation.check_imports_resolve(_index(root)) is None


# --- foundation.entrypoint.parses --------------------------------------------

def test_entrypoint_parses_valid_entrypoints_pass(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": "# Overview\n\nFine.\n",
        ".github/copilot-instructions.md": "# Overview\n\nAlso fine.\n",
    })
    sat, diags = foundation.check_entrypoint_parses(_index(root))
    assert sat == 1.0
    assert diags == []


def test_entrypoint_parses_malformed_frontmatter_is_error(tmp_path):
    root = _repo(tmp_path, {
        "CLAUDE.md": "---\nkey: [unclosed\n---\nBody text.\n",
    })
    sat, diags = foundation.check_entrypoint_parses(_index(root))
    assert sat == 0.0
    assert len(diags) == 1
    rel_path, diag = diags[0]
    assert rel_path == PurePosixPath("CLAUDE.md")
    assert diag.severity == Severity.ERROR


def test_entrypoint_parses_undecodable_utf8_is_error(tmp_path):
    root = _repo(tmp_path, {"CLAUDE.md": "# Fine\n"})
    bad = root / ".github" / "copilot-instructions.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"\xff\xfe not utf-8")
    sat, diags = foundation.check_entrypoint_parses(_index(root))
    assert sat == 0.0
    assert len(diags) == 1
    assert diags[0][0] == PurePosixPath(".github/copilot-instructions.md")


def test_entrypoint_parses_not_applicable_without_entrypoint_artifacts(tmp_path):
    # AGENTS.md is not an ENTRYPOINT_* artifact kind, so the rule stays N/A.
    root = _repo(tmp_path, {"AGENTS.md": "# Agents\n"})
    assert foundation.check_entrypoint_parses(_index(root)) is None


# --- metadata backfill --------------------------------------------------------

def test_foundation_metadata_backfill():
    assert get_rule("foundation.copilot.entrypoint").platforms == (Platform.COPILOT,)
    assert get_rule("foundation.claude.entrypoint").platforms == (Platform.CLAUDE,)
    assert get_rule("foundation.agentsmd.bridged").platforms == (Platform.CLAUDE,)
    assert get_rule("foundation.agentsmd.bridged").effort == "mechanical"
    assert get_rule("foundation.entrypoint.present").platforms == (
        Platform.COPILOT, Platform.CLAUDE,
    )
    for meta_id in (
        "foundation.entrypoint.present",
        "foundation.copilot.entrypoint",
        "foundation.claude.entrypoint",
        "foundation.agentsmd.bridged",
        "foundation.entrypoint.length",
        "foundation.entrypoint.structured",
        "foundation.sections.coverage",
        "foundation.imports.resolve",
        "foundation.entrypoint.parses",
    ):
        meta = get_rule(meta_id)
        assert meta.why and meta.fix and meta.effort
