"""Tests for the verification pillar rules (plan-v2-fable.md §4.6).

Each rule gets at least one satisfied, one violated, and — where the spec
allows it — one not-applicable (None) case. `verify.test-command.documented`,
`verify.test-suite.exists`, `verify.ci.exists`, and `verify.hooks.present`
are always applicable by spec, so they have no N/A case.
"""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import Severity
import airx.rules.verification as verification

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _index_of(root: Path):
    return build_index(fs.scan(root))


def _repo(tmp_path: Path, files: dict[str, str]):
    root = tmp_path / "repo"
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return _index_of(root)


def _fixture_index():
    return _index_of(FIXTURES / "repo_verification_rich")


# --- verify.test-command.documented ------------------------------------------


def test_test_command_documented_and_resolving():
    sat, diags = verification.check_test_command_documented(_fixture_index())
    assert sat == 1.0
    assert diags == []


def test_test_command_not_documented(tmp_path):
    index = _repo(tmp_path, {
        "CLAUDE.md": "# Repo\n\nJust prose, no commands.\n",
        "pytest.ini": "[pytest]\n",
        "tests/test_a.py": "def test_a():\n    assert True\n",
    })
    sat, diags = verification.check_test_command_documented(index)
    assert sat == 0.0
    assert "No test command" in diags[0].message


def test_test_command_documented_but_unresolvable(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nRun `pytest` when done.\n"})
    sat, diags = verification.check_test_command_documented(index)
    assert sat == 0.0
    assert "does not resolve" in diags[0].message


def test_test_command_via_package_script_in_fenced_block(tmp_path):
    index = _repo(tmp_path, {
        "package.json": '{"scripts": {"test:unit": "vitest run"}}',
        "tests/unit.spec.ts": "export {}\n",
        "CLAUDE.md": "# Repo\n\n## Commands\n\n```bash\nnpm run test:unit\n```\n",
    })
    sat, diags = verification.check_test_command_documented(index)
    assert sat == 1.0
    assert diags == []


# --- verify.build-command.documented -----------------------------------------


def test_build_command_na_without_build_evidence(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nRun `pytest`.\n"})
    assert verification.check_build_command_documented(index) is None


def test_build_command_documented_via_package_script(tmp_path):
    index = _repo(tmp_path, {
        "package.json": '{"scripts": {"build": "tsc"}}',
        "CLAUDE.md": "# Repo\n\nBuild with `npm run build`.\n",
    })
    sat, diags = verification.check_build_command_documented(index)
    assert sat == 1.0
    assert diags == []


def test_build_command_documented_via_bare_token(tmp_path):
    index = _repo(tmp_path, {
        "Cargo.toml": '[package]\nname = "x"\n',
        "CLAUDE.md": "# Repo\n\nRun `cargo build` to compile.\n",
    })
    sat, diags = verification.check_build_command_documented(index)
    assert sat == 1.0
    assert diags == []


def test_build_command_missing_when_build_system_exists(tmp_path):
    index = _repo(tmp_path, {
        "package.json": '{"scripts": {"build": "tsc"}}',
        "CLAUDE.md": "# Repo\n\nNo commands documented here.\n",
    })
    sat, diags = verification.check_build_command_documented(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


# --- verify.lint-command.documented ------------------------------------------


def test_lint_command_na_without_lint_config(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nRun `pytest`.\n"})
    assert verification.check_lint_command_documented(index) is None


def test_lint_command_documented_via_make_target():
    sat, diags = verification.check_lint_command_documented(_fixture_index())
    assert sat == 1.0
    assert diags == []


def test_lint_command_missing_when_lint_config_exists(tmp_path):
    index = _repo(tmp_path, {
        ".eslintrc.json": "{}",
        "CLAUDE.md": "# Repo\n\nRun `npm run deploy` to ship.\n",
    })
    sat, diags = verification.check_lint_command_documented(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


# --- verify.test-suite.exists ------------------------------------------------


def test_test_suite_exists_satisfied():
    sat, diags = verification.check_test_suite_exists(_fixture_index())
    assert sat == 1.0
    assert diags == []


def test_test_suite_missing(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nProse only.\n"})
    sat, diags = verification.check_test_suite_exists(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


# --- verify.ci.exists --------------------------------------------------------


def test_ci_exists_satisfied():
    sat, diags = verification.check_ci_exists(_fixture_index())
    assert sat == 1.0
    assert diags == []


def test_ci_missing(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nProse only.\n"})
    sat, diags = verification.check_ci_exists(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


# --- verify.loop.instructed --------------------------------------------------


def test_loop_instructed_two_cues_full_credit():
    sat, diags = verification.check_loop_instructed(_fixture_index())
    assert sat == 1.0
    assert diags == []


def test_loop_instructed_single_cue_half_credit(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nAlways verify your work before finishing.\n"})
    sat, diags = verification.check_loop_instructed(index)
    assert sat == 0.5
    assert len(diags) == 1


def test_loop_instructed_absent(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nBe kind to reviewers.\n"})
    sat, diags = verification.check_loop_instructed(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


def test_loop_instructed_na_without_entrypoint(tmp_path):
    index = _repo(tmp_path, {"README.md": "# Repo\n"})
    assert verification.check_loop_instructed(index) is None


# --- verify.hooks.present ----------------------------------------------------


def test_hooks_present_via_github_hooks_file(tmp_path):
    index = _repo(tmp_path, {
        ".github/hooks/checks.json":
            '{"version": 1, "hooks": {"preToolUse": [{"type": "command", "bash": "./check.sh"}]}}',
    })
    sat, diags = verification.check_hooks_present(index)
    assert sat == 1.0
    assert diags == []


def test_hooks_present_via_claude_settings(tmp_path):
    index = _repo(tmp_path, {".claude/settings.json": '{"hooks": {"PostToolUse": []}}'})
    sat, diags = verification.check_hooks_present(index)
    assert sat == 1.0
    assert diags == []


def test_hooks_absent(tmp_path):
    index = _repo(tmp_path, {"README.md": "# Repo\n"})
    sat, diags = verification.check_hooks_present(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


# --- verify.hooks.schema -----------------------------------------------------


def test_hooks_schema_valid_list_and_dict_entries(tmp_path):
    index = _repo(tmp_path, {
        ".github/hooks/a.json":
            '{"version": 1, "hooks": {"preToolUse": [{"type": "command", "bash": "./check.sh"}]}}',
        ".github/hooks/b.json":
            '{"version": 1, "hooks": {"postToolUse": {"type": "command", "powershell": "check.ps1"}}}',
    })
    sat, diags = verification.check_hooks_schema(index)
    assert sat == 1.0
    assert diags == []


def test_hooks_schema_invalid_file(tmp_path):
    index = _repo(tmp_path, {
        ".github/hooks/bad.json": '{"version": 2, "hooks": {"pre": {"type": "shell"}}}',
    })
    sat, diags = verification.check_hooks_schema(index)
    assert sat == 0.0
    # version != 1, type != command, and no bash/powershell key -> 3 findings
    assert len(diags) == 3
    for rel_path, diag in diags:
        assert rel_path == PurePosixPath(".github/hooks/bad.json")
        assert diag.severity == Severity.ERROR


def test_hooks_schema_parse_error_scores_zero(tmp_path):
    index = _repo(tmp_path, {".github/hooks/broken.json": "{not json"})
    sat, diags = verification.check_hooks_schema(index)
    assert sat == 0.0
    assert "JSON" in diags[0][1].message


def test_hooks_schema_mean_over_files(tmp_path):
    index = _repo(tmp_path, {
        ".github/hooks/good.json":
            '{"version": 1, "hooks": {"preToolUse": [{"type": "command", "bash": "./check.sh"}]}}',
        ".github/hooks/nohooks.json": '{"version": 1}',
    })
    sat, diags = verification.check_hooks_schema(index)
    assert sat == 0.5
    assert len(diags) == 1


def test_hooks_schema_na_without_hook_files(tmp_path):
    index = _repo(tmp_path, {"README.md": "# Repo\n"})
    assert verification.check_hooks_schema(index) is None


# --- verify.evidence.instructed ----------------------------------------------


def test_evidence_instructed_satisfied():
    sat, diags = verification.check_evidence_instructed(_fixture_index())
    assert sat == 1.0
    assert diags == []


def test_evidence_not_instructed(tmp_path):
    index = _repo(tmp_path, {"CLAUDE.md": "# Repo\n\nBe kind to reviewers.\n"})
    sat, diags = verification.check_evidence_instructed(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


def test_evidence_na_without_entrypoint(tmp_path):
    index = _repo(tmp_path, {"README.md": "# Repo\n"})
    assert verification.check_evidence_instructed(index) is None
