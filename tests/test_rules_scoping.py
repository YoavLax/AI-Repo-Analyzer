"""Tests for the scoping pillar rules (plan-v2-fable.md §4.4).

Each test builds a tiny repository (in tmp_path or from a committed fixture),
runs discovery, and calls the rule functions directly.
"""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import Diagnostic, Severity
import airx.rules.scoping as scoping

FIXTURES = Path(__file__).parent / "fixtures"


def _index(root: Path):
    return build_index(fs.scan(root))


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _instructions(applyto_line: str) -> str:
    fm = f"---\n{applyto_line}\n---\n" if applyto_line else "---\ndescription: x\n---\n"
    return fm + "\n# Area conventions\n\n- Keep it small.\n"


# --- _glob_match -------------------------------------------------------------

def test_glob_match_double_star_crosses_separators():
    assert scoping._glob_match("**", "deep/nested/dir/file.py")
    assert scoping._glob_match("**/*.py", "src/app.py")
    assert scoping._glob_match("src/**", "src/a/b/c.txt")


def test_glob_match_single_star_stays_in_segment():
    assert scoping._glob_match("*.py", "app.py")
    assert not scoping._glob_match("*.py", "src/app.py")


def test_glob_match_question_mark_one_char():
    assert scoping._glob_match("src/?.py", "src/a.py")
    assert not scoping._glob_match("src/?.py", "src/ab.py")


def test_glob_match_is_fully_anchored_and_escapes_literals():
    assert not scoping._glob_match("app", "app.py")
    assert not scoping._glob_match("src", "src/app.py")
    assert not scoping._glob_match("a.b", "axb")  # '.' is literal, not regex


# --- scoping.scoped-files.present -------------------------------------------
# Presence rule: always applicable, so there is no N/A case.

def test_scoped_files_present_satisfied_by_instructions_fixture():
    sat, diags = scoping.check_scoped_files_present(_index(FIXTURES / "repo_scoped_ok"))
    assert sat == 1.0
    assert diags == []


def test_scoped_files_present_violated_without_scoped_files(tmp_path):
    _write(tmp_path, ".github/copilot-instructions.md", "# Rules\n\n- Be specific.\n")
    _write(tmp_path, "AGENTS.md", "# Agents\n")  # root AGENTS.md is not nested
    sat, diags = scoping.check_scoped_files_present(_index(tmp_path))
    assert sat == 0.0
    assert len(diags) == 1
    assert diags[0].severity == Severity.WARNING


def test_scoped_files_present_satisfied_by_nested_agents_md(tmp_path):
    _write(tmp_path, "AGENTS.md", "# Agents\n")
    _write(tmp_path, "docs/AGENTS.md", "# Docs agents\n")
    sat, diags = scoping.check_scoped_files_present(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_scoped_files_present_satisfied_by_claude_rule(tmp_path):
    _write(tmp_path, ".claude/rules/style.md", "# Style\n\n- Two-space indent.\n")
    sat, diags = scoping.check_scoped_files_present(_index(tmp_path))
    assert sat == 1.0


# --- scoping.applyto.declared ------------------------------------------------

def test_applyto_declared_satisfied_on_fixture():
    sat, diags = scoping.check_applyto_declared(_index(FIXTURES / "repo_scoped_ok"))
    assert sat == 1.0
    assert diags == []


def test_applyto_declared_violated_on_fixture():
    sat, diags = scoping.check_applyto_declared(
        _index(FIXTURES / "repo_scoped_missing_applyto"))
    assert sat == 0.0
    assert len(diags) == 1
    rel_path, diag = diags[0]  # per-file diagnostics are (rel_path, Diagnostic)
    assert rel_path == PurePosixPath(".github/instructions/python.instructions.md")
    assert isinstance(diag, Diagnostic)
    assert diag.severity == Severity.ERROR


def test_applyto_declared_not_applicable_without_instructions(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert scoping.check_applyto_declared(_index(tmp_path)) is None


def test_applyto_declared_per_file_mean(tmp_path):
    _write(tmp_path, ".github/instructions/a.instructions.md",
           _instructions('applyTo: "**/*.py"'))
    _write(tmp_path, ".github/instructions/b.instructions.md", _instructions(""))
    _write(tmp_path, "src/app.py", "print('hi')\n")
    sat, diags = scoping.check_applyto_declared(_index(tmp_path))
    assert sat == 0.5
    assert len(diags) == 1
    assert diags[0][0] == PurePosixPath(".github/instructions/b.instructions.md")


def test_applyto_declared_counts_unparseable_file_as_violation(tmp_path):
    _write(tmp_path, ".github/instructions/bad.instructions.md",
           "---\napplyTo: [oops\n---\n\n# Broken\n")
    sat, diags = scoping.check_applyto_declared(_index(tmp_path))
    assert sat == 0.0
    assert diags[0][0] == PurePosixPath(".github/instructions/bad.instructions.md")
    assert diags[0][1].severity == Severity.ERROR


def test_applyto_declared_empty_string_is_violation(tmp_path):
    _write(tmp_path, ".github/instructions/e.instructions.md",
           _instructions('applyTo: ""'))
    sat, diags = scoping.check_applyto_declared(_index(tmp_path))
    assert sat == 0.0
    assert len(diags) == 1


# --- scoping.applyto.matches -------------------------------------------------

def test_applyto_matches_satisfied_on_fixture():
    sat, diags = scoping.check_applyto_matches(_index(FIXTURES / "repo_scoped_ok"))
    assert sat == 1.0
    assert diags == []


def test_applyto_matches_violated_when_glob_matches_nothing(tmp_path):
    _write(tmp_path, ".github/instructions/rust.instructions.md",
           _instructions('applyTo: "**/*.rs"'))
    _write(tmp_path, "src/app.py", "print('hi')\n")
    sat, diags = scoping.check_applyto_matches(_index(tmp_path))
    assert sat == 0.0
    assert len(diags) == 1
    rel_path, diag = diags[0]
    assert rel_path == PurePosixPath(".github/instructions/rust.instructions.md")
    assert diag.severity == Severity.WARNING


def test_applyto_matches_not_applicable_without_instructions(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert scoping.check_applyto_matches(_index(tmp_path)) is None


def test_applyto_matches_not_applicable_when_no_globs_declared():
    # Instructions exist but declare no applyTo: nothing to match (the
    # declared rule owns that failure).
    assert scoping.check_applyto_matches(
        _index(FIXTURES / "repo_scoped_missing_applyto")) is None


def test_applyto_matches_comma_separated_partial(tmp_path):
    _write(tmp_path, ".github/instructions/mix.instructions.md",
           _instructions('applyTo: "**/*.py, **/*.rs"'))
    _write(tmp_path, "src/app.py", "print('hi')\n")
    sat, diags = scoping.check_applyto_matches(_index(tmp_path))
    assert sat == 0.5
    assert len(diags) == 1
    assert "**/*.rs" in diags[0][1].message


def test_applyto_matches_yaml_list(tmp_path):
    _write(tmp_path, ".github/instructions/list.instructions.md",
           _instructions('applyTo:\n  - "**/*.py"\n  - "src/**"'))
    _write(tmp_path, "src/app.py", "print('hi')\n")
    sat, diags = scoping.check_applyto_matches(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


# --- scoping.applyto.not-universal -------------------------------------------

def test_applyto_not_universal_single_universal_file_ok(tmp_path):
    _write(tmp_path, ".github/instructions/all.instructions.md",
           _instructions("applyTo: '**'"))
    sat, diags = scoping.check_applyto_not_universal(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_applyto_not_universal_violated_flags_second_plus_files(tmp_path):
    _write(tmp_path, ".github/instructions/a.instructions.md",
           _instructions("applyTo: '**'"))
    _write(tmp_path, ".github/instructions/b.instructions.md",
           _instructions("applyTo: '**'"))
    sat, diags = scoping.check_applyto_not_universal(_index(tmp_path))
    assert sat == 0.0
    assert len(diags) == 1  # only the second+ files get diagnostics
    rel_path, diag = diags[0]
    assert rel_path == PurePosixPath(".github/instructions/b.instructions.md")
    assert diag.severity == Severity.INFO


def test_applyto_not_universal_not_applicable_without_instructions(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert scoping.check_applyto_not_universal(_index(tmp_path)) is None


def test_applyto_not_universal_scoped_globs_pass():
    sat, diags = scoping.check_applyto_not_universal(_index(FIXTURES / "repo_scoped_ok"))
    assert sat == 1.0
    assert diags == []


# --- scoping.monolith --------------------------------------------------------

def _long_entrypoint(lines: int = 260) -> str:
    return "# Big\n" + ("Guidance line.\n" * (lines - 1))


def test_monolith_violated_long_entrypoint_no_scoped_files(tmp_path):
    _write(tmp_path, "CLAUDE.md", _long_entrypoint())
    sat, diags = scoping.check_monolith(_index(tmp_path))
    assert sat == 0.0
    assert len(diags) == 1
    assert diags[0].severity == Severity.WARNING


def test_monolith_ok_when_scoped_files_exist(tmp_path):
    _write(tmp_path, "CLAUDE.md", _long_entrypoint())
    _write(tmp_path, ".github/instructions/py.instructions.md",
           _instructions('applyTo: "**/*.py"'))
    sat, diags = scoping.check_monolith(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_monolith_ok_when_entrypoint_short(tmp_path):
    _write(tmp_path, "CLAUDE.md", "# Small\n\n- Be concise.\n")
    sat, diags = scoping.check_monolith(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_monolith_not_applicable_without_entrypoint(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert scoping.check_monolith(_index(tmp_path)) is None
