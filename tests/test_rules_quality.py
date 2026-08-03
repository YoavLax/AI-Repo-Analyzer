"""Tests for the quality pillar rules (plan-v2-fable.md §4.3).

Each rule is exercised directly against an ArtifactIndex built from a tiny
repository written into tmp_path (plus the committed repo_quality_rich
fixture): one satisfied case, one violated case, and one not-applicable case
per rule.
"""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import Diagnostic, Severity
import airx.rules.quality as quality

FIXTURES = Path(__file__).parent / "fixtures"

_CONCRETE_DIRECTIVES = (
    "# Guidelines\n"
    "\n"
    "- Run `pytest -q` before pushing because CI enforces it\n"
    "- Keep modules under `src/airx/` small\n"
    "- Use `ruff check` on all source files\n"
    "- Support Python 3.11 and newer runtimes\n"
)

_VAGUE_DIRECTIVES = (
    "# Guidelines\n"
    "\n"
    "- Keep the code readable and clear\n"
    "- Prefer short functions where possible\n"
    "- Avoid overly clever solutions\n"
    "- Name things in a sensible way\n"
)


def _write(tmp_path: Path, rel: str, text: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _index(tmp_path: Path):
    return build_index(fs.scan(tmp_path))


def _entry(tmp_path: Path, text: str):
    _write(tmp_path, "CLAUDE.md", text)
    return _index(tmp_path)


# --- quality.specificity.index ------------------------------------------------

def test_specificity_satisfied_by_concrete_directives(tmp_path):
    index = _entry(tmp_path, _CONCRETE_DIRECTIVES)
    sat, diags = quality.check_specificity_index(index)
    assert sat == 1.0
    assert diags == []


def test_specificity_zero_for_vague_directives(tmp_path):
    index = _entry(tmp_path, _VAGUE_DIRECTIVES)
    sat, diags = quality.check_specificity_index(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")
    assert diag.severity == Severity.WARNING


def test_specificity_graded_against_target(tmp_path):
    # 1 concrete of 4 directives => ratio 0.25, sat = 0.25 / 0.5 = 0.5.
    index = _entry(
        tmp_path,
        "# G\n\n"
        "- Run `pytest -q` before pushing work\n"
        "- Keep the code readable and clear\n"
        "- Avoid overly clever solutions\n"
        "- Name things in a sensible way\n",
    )
    sat, _diags = quality.check_specificity_index(index)
    assert sat == 0.5


def test_specificity_not_applicable_below_min_directives(tmp_path):
    index = _entry(tmp_path, "# G\n\n- Keep the code readable and clear\n")
    assert quality.check_specificity_index(index) is None


def test_specificity_not_applicable_without_docs(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert quality.check_specificity_index(_index(tmp_path)) is None


def test_directives_inside_fenced_blocks_are_ignored(tmp_path):
    index = _entry(
        tmp_path,
        "# G\n\n"
        "- Real directive number one here\n"
        "- Real directive number two here\n"
        "\n"
        "```text\n"
        "- fake directive inside fence one\n"
        "- fake directive inside fence two\n"
        "```\n",
    )
    # Only 2 real directives survive fence stripping => below the minimum.
    assert quality.check_specificity_index(index) is None


def test_multi_file_mean_aggregation_with_instructions(tmp_path):
    _write(tmp_path, ".github/copilot-instructions.md", _CONCRETE_DIRECTIVES)
    _write(tmp_path, ".github/instructions/api.instructions.md", _VAGUE_DIRECTIVES)
    sat, diags = quality.check_specificity_index(_index(tmp_path))
    assert sat == 0.5  # mean of 1.0 (entry point) and 0.0 (instructions)
    assert len(diags) == 1
    rel, diag = diags[0]
    assert rel == PurePosixPath(".github/instructions/api.instructions.md")


# --- quality.rationale.present ------------------------------------------------

def test_rationale_satisfied_at_target_ratio(tmp_path):
    # 1 of 4 directives carries a rationale => ratio 0.25 == target => 1.0.
    index = _entry(tmp_path, _CONCRETE_DIRECTIVES)
    sat, diags = quality.check_rationale_present(index)
    assert sat == 1.0
    assert diags == []


def test_rationale_zero_without_rationale_markers(tmp_path):
    index = _entry(tmp_path, _VAGUE_DIRECTIVES)
    sat, diags = quality.check_rationale_present(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")


def test_rationale_not_applicable_below_min_directives(tmp_path):
    index = _entry(tmp_path, "# G\n\n- Run `pytest -q` before pushing work\n")
    assert quality.check_rationale_present(index) is None


# --- quality.examples.present -------------------------------------------------

def test_examples_satisfied_by_fenced_block(tmp_path):
    index = _entry(tmp_path, "# G\n\nPreferred:\n\n```python\nprint('x')\n```\n")
    sat, diags = quality.check_examples_present(index)
    assert sat == 1.0
    assert diags == []


def test_examples_satisfied_by_preferred_avoided_pair(tmp_path):
    index = _entry(tmp_path, "# G\n\nUse pathlib instead of os.path everywhere.\n")
    sat, diags = quality.check_examples_present(index)
    assert sat == 1.0


def test_examples_violated_without_example_or_pair(tmp_path):
    index = _entry(tmp_path, _VAGUE_DIRECTIVES.replace("Prefer", "Favor"))
    sat, diags = quality.check_examples_present(index)
    assert sat == 0.0
    assert isinstance(diags[0], Diagnostic)  # repo-level, bare diagnostic


def test_examples_not_applicable_without_docs(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert quality.check_examples_present(_index(tmp_path)) is None


# --- quality.no-obvious-rules -------------------------------------------------

def test_no_obvious_rules_satisfied(tmp_path):
    index = _entry(tmp_path, _CONCRETE_DIRECTIVES)
    sat, diags = quality.check_no_obvious_rules(index)
    assert sat == 1.0
    assert diags == []


def test_no_obvious_rules_flags_truisms(tmp_path):
    index = _entry(
        tmp_path,
        "# G\n\n"
        "- Write clean code in every module\n"
        "- Follow best practices for the team\n"
        "- Run `pytest -q` before pushing anything\n"
        "- Keep modules under `src/` small and cohesive\n",
    )
    sat, diags = quality.check_no_obvious_rules(index)
    assert sat == 0.5  # 2 of 4 directives flagged
    assert len(diags) == 2
    assert all(rel == PurePosixPath("CLAUDE.md") for rel, _d in diags)
    assert diags[0][1].line is not None


def test_no_obvious_rules_not_applicable_below_min_directives(tmp_path):
    index = _entry(tmp_path, "# G\n\n- Write clean code in every module\n")
    assert quality.check_no_obvious_rules(index) is None


# --- quality.directive.atomicity ----------------------------------------------

def test_atomicity_satisfied_by_short_directives(tmp_path):
    index = _entry(tmp_path, _CONCRETE_DIRECTIVES)
    sat, diags = quality.check_directive_atomicity(index)
    assert sat == 1.0
    assert diags == []


def test_atomicity_flags_overlong_directive(tmp_path):
    long_directive = "- " + "word " * 50  # 251 visible characters stripped
    index = _entry(
        tmp_path,
        "# G\n\n"
        f"{long_directive}\n"
        "- Keep the code readable and clear\n"
        "- Avoid overly clever solutions\n"
        "- Name things in a sensible way\n",
    )
    sat, diags = quality.check_directive_atomicity(index)
    assert sat == 0.75  # 1 of 4 flagged
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")
    assert "251" in diag.message


def test_atomicity_not_applicable_below_min_directives(tmp_path):
    index = _entry(tmp_path, "# G\n\n- Keep the code readable and clear\n")
    assert quality.check_directive_atomicity(index) is None


# --- quality.emphasis.calibrated ----------------------------------------------

def test_emphasis_satisfied_below_ceiling(tmp_path):
    index = _entry(
        tmp_path,
        "# G\n\n"
        "- NEVER commit directly to the main branch\n"
        "- Keep the code readable and clear\n"
        "- Avoid overly clever solutions\n"
        "- Name things in a sensible way\n"
        "- Keep functions short and focused\n",
    )
    sat, diags = quality.check_emphasis_calibrated(index)
    assert sat == 1.0  # 1 of 5 directives emphasized (20% <= 30%)
    assert diags == []


def test_emphasis_violated_above_ceiling(tmp_path):
    index = _entry(
        tmp_path,
        "# G\n\n"
        "- NEVER commit directly to the main branch\n"
        "- IMPORTANT: update the changelog for releases\n"
        "- Keep the code readable and clear\n"
        "- Avoid overly clever solutions\n"
        "- Name things in a sensible way\n",
    )
    sat, diags = quality.check_emphasis_calibrated(index)
    assert sat == 0.0  # 2 of 5 directives emphasized (40% > 30%)
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")


def test_emphasis_not_applicable_below_five_directives(tmp_path):
    index = _entry(
        tmp_path,
        "# G\n\n"
        "- NEVER commit directly to the main branch\n"
        "- IMPORTANT: update the changelog for releases\n"
        "- ALWAYS run the linter before pushing\n"
        "- CRITICAL: keep secrets out of the repo\n",
    )
    assert quality.check_emphasis_calibrated(index) is None


# --- quality.no-stale-markers -------------------------------------------------

def test_no_stale_markers_satisfied(tmp_path):
    index = _entry(tmp_path, _CONCRETE_DIRECTIVES)
    sat, diags = quality.check_no_stale_markers(index)
    assert sat == 1.0
    assert diags == []


def test_no_stale_markers_flags_todo(tmp_path):
    index = _entry(tmp_path, "# G\n\nTODO: describe the deployment process.\n")
    sat, diags = quality.check_no_stale_markers(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")
    assert "TODO" in diag.message


def test_no_stale_markers_not_applicable_without_docs(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert quality.check_no_stale_markers(_index(tmp_path)) is None


# --- quality.links.resolve ----------------------------------------------------

def test_links_resolve_satisfied(tmp_path):
    _write(tmp_path, "docs/guide.md", "# Guide\n")
    index = _entry(tmp_path, "# G\n\nSee [the guide](docs/guide.md) first.\n")
    sat, diags = quality.check_links_resolve(index)
    assert sat == 1.0
    assert diags == []


def test_links_resolve_flags_missing_target(tmp_path):
    index = _entry(tmp_path, "# G\n\nSee [the guide](docs/missing.md) first.\n")
    sat, diags = quality.check_links_resolve(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")
    assert "docs/missing.md" in diag.message


def test_links_resolve_flags_escaping_target(tmp_path):
    index = _entry(tmp_path, "# G\n\nSee [outside](../outside.md) for more.\n")
    sat, diags = quality.check_links_resolve(index)
    assert sat == 0.0
    _rel, diag = diags[0]
    assert "escapes" in diag.message


def test_links_resolve_not_applicable_without_relative_links(tmp_path):
    index = _entry(
        tmp_path,
        "# G\n\nSee [site](https://example.com), [mail](mailto:a@b.c), "
        "and [below](#guidelines).\n",
    )
    assert quality.check_links_resolve(index) is None


def test_links_resolve_accepts_repo_root_relative_link_from_subdir_entrypoint(tmp_path):
    # A link written in .github/copilot-instructions.md as "src/foo.ts" is a
    # common convention meaning "repo-root-relative", even though it resolves
    # to .github/src/foo.ts (and 404s) under strict browser link semantics.
    # Agents resolve paths via their file-access tools using the repo root,
    # so this must not be flagged.
    _write(tmp_path, "src/foo.ts", "export {};\n")
    _write(
        tmp_path, ".github/copilot-instructions.md",
        "# Instructions\n\n- [src/foo.ts](src/foo.ts) - does the thing\n",
    )
    index = _index(tmp_path)
    sat, diags = quality.check_links_resolve(index)
    assert sat == 1.0
    assert diags == []


def test_links_resolve_still_flags_link_missing_under_both_interpretations(tmp_path):
    _write(
        tmp_path, ".github/copilot-instructions.md",
        "# Instructions\n\n- [src/missing.ts](src/missing.ts) - nope\n",
    )
    index = _index(tmp_path)
    sat, diags = quality.check_links_resolve(index)
    assert sat == 0.0
    _rel, diag = diags[0]
    assert "src/missing.ts" in diag.message


# --- committed fixture: repo_quality_rich -------------------------------------

def test_repo_quality_rich_scores_well_across_all_rules():
    index = build_index(fs.scan(FIXTURES / "repo_quality_rich"))

    assert quality.check_specificity_index(index) == (1.0, [])
    assert quality.check_rationale_present(index) == (1.0, [])
    assert quality.check_examples_present(index) == (1.0, [])
    assert quality.check_no_obvious_rules(index) == (1.0, [])
    assert quality.check_directive_atomicity(index) == (1.0, [])
    assert quality.check_emphasis_calibrated(index) == (1.0, [])
    assert quality.check_no_stale_markers(index) == (1.0, [])
    assert quality.check_links_resolve(index) is None  # no relative links


# --- quality.entrypoint.no-lint-rules (v0.3.0) -------------------------------

def test_no_lint_rules_satisfied_without_style_phrases(tmp_path):
    index = _entry(tmp_path, "# Guidelines\n\n- Run `pytest -q` before pushing\n")
    sat, diags = quality.check_entrypoint_no_lint_rules(index)
    assert sat == 1.0
    assert diags == []


def test_no_lint_rules_flags_multiple_style_phrases(tmp_path):
    index = _entry(
        tmp_path,
        "# Style\n\n- Use single quotes everywhere\n- Use 2 space indent\n"
        "- No trailing whitespace\n",
    )
    sat, diags = quality.check_entrypoint_no_lint_rules(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath("CLAUDE.md")
    assert diag.severity == Severity.INFO
    assert "single quotes" in diag.message  # plain phrase, not a regex-escaped source


def test_no_lint_rules_ignores_phrases_inside_code_fences(tmp_path):
    index = _entry(
        tmp_path,
        "# Style\n\n```json\n"
        '{"note": "single quotes, 2 space indent, trailing comma"}\n'
        "```\n",
    )
    sat, diags = quality.check_entrypoint_no_lint_rules(index)
    assert sat == 1.0
    assert diags == []


def test_no_lint_rules_single_mention_passes(tmp_path):
    index = _entry(tmp_path, "# Style\n\n- Use single quotes for strings\n")
    sat, diags = quality.check_entrypoint_no_lint_rules(index)
    assert sat == 1.0
    assert diags == []


def test_no_lint_rules_not_applicable_without_docs(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    assert quality.check_entrypoint_no_lint_rules(_index(tmp_path)) is None


# --- quality.references.pointers-not-snippets (v0.3.0) -----------------------

def test_pointers_not_snippets_satisfied_with_small_reference(tmp_path):
    _write(tmp_path, "docs/testing.md", "# Testing\n\n```python\nassert True\n```\n")
    index = _entry(tmp_path, "# G\n\nSee [testing](docs/testing.md) for conventions.\n")
    sat, diags = quality.check_references_pointers_not_snippets(index)
    assert sat == 1.0
    assert diags == []


def test_pointers_not_snippets_flags_oversized_code_block(tmp_path):
    big_block = "\n".join(f"line {i}" for i in range(60))
    _write(tmp_path, "docs/testing.md", f"# Testing\n\n```python\n{big_block}\n```\n")
    index = _entry(tmp_path, "# G\n\nSee [testing](docs/testing.md) for conventions.\n")
    sat, diags = quality.check_references_pointers_not_snippets(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath("docs/testing.md")
    assert diag.severity == Severity.INFO


def test_pointers_not_snippets_not_applicable_without_markdown_references(tmp_path):
    index = _entry(tmp_path, "# G\n\nNo links here.\n")
    assert quality.check_references_pointers_not_snippets(index) is None
