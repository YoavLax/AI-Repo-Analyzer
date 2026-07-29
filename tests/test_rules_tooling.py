"""Tests for the tooling pillar rules (plan-v2-fable.md §4.7).

Each rule is exercised directly against an ArtifactIndex built from either a
tiny repo written into tmp_path or one of the committed tooling fixtures.
"""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import Severity
from airx.rules import tooling as rules

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PKG_THREE_SCRIPTS = '{"scripts": {"build": "tsc", "test": "vitest", "lint": "eslint ."}}'


def _index(root: Path):
    return build_index(fs.scan(root))


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- tooling.mcp.present -----------------------------------------------------

def test_mcp_present_satisfied_by_fixture():
    sat, diags = rules.check_mcp_present(_index(FIXTURES / "repo_tooling_mcp"))
    assert sat == 1.0
    assert diags == []


def test_mcp_present_violated_without_config(tmp_path):
    _write(tmp_path, "README.md", "# hello\n")
    sat, diags = rules.check_mcp_present(_index(tmp_path))
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


# --- tooling.mcp.valid -------------------------------------------------------

def test_mcp_valid_satisfied_by_fixture():
    sat, diags = rules.check_mcp_valid(_index(FIXTURES / "repo_tooling_mcp"))
    assert sat == 1.0
    assert diags == []


def test_mcp_valid_unparseable_json_scores_zero(tmp_path):
    _write(tmp_path, ".mcp.json", "{ this is not json")
    sat, diags = rules.check_mcp_valid(_index(tmp_path))
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".mcp.json")
    assert diag.severity == Severity.ERROR


def test_mcp_valid_server_missing_command_and_url(tmp_path):
    _write(tmp_path, ".mcp.json", '{"mcpServers": {"broken": {"args": ["-y"]}}}')
    sat, diags = rules.check_mcp_valid(_index(tmp_path))
    assert sat == 0.0
    assert "broken" in diags[0][1].message


def test_mcp_valid_per_file_mean(tmp_path):
    _write(tmp_path, ".mcp.json", '{"mcpServers": {"ok": {"url": "https://example.com/mcp"}}}')
    _write(tmp_path, ".vscode/mcp.json", '{"servers": {"bad": {}}}')
    sat, diags = rules.check_mcp_valid(_index(tmp_path))
    assert sat == 0.5
    assert len(diags) == 1
    assert diags[0][0] == PurePosixPath(".vscode/mcp.json")


def test_mcp_valid_not_applicable_without_mcp(tmp_path):
    _write(tmp_path, "README.md", "# hello\n")
    assert rules.check_mcp_valid(_index(tmp_path)) is None


# --- tooling.mcp.no-secrets --------------------------------------------------

def test_mcp_no_secrets_env_indirection_passes():
    sat, diags = rules.check_mcp_no_secrets(_index(FIXTURES / "repo_tooling_mcp"))
    assert sat == 1.0
    assert diags == []


def test_mcp_no_secrets_flags_token_fixture():
    sat, diags = rules.check_mcp_no_secrets(_index(FIXTURES / "repo_tooling_mcp_secret"))
    assert sat == 0.0
    assert diags
    assert {rel for rel, _ in diags} == {PurePosixPath(".mcp.json")}
    assert all(d.severity == Severity.ERROR for _, d in diags)


def test_mcp_no_secrets_flags_long_env_literal(tmp_path):
    _write(
        tmp_path, ".mcp.json",
        '{"mcpServers": {"db": {"command": "run-db", '
        '"env": {"DB_PASSWORD": "supersecretpassword123"}}}}',
    )
    sat, diags = rules.check_mcp_no_secrets(_index(tmp_path))
    assert sat == 0.0
    assert "DB_PASSWORD" in diags[0][1].message


def test_mcp_no_secrets_short_env_literal_passes(tmp_path):
    _write(
        tmp_path, ".mcp.json",
        '{"mcpServers": {"db": {"command": "run-db", "env": {"MODE": "production"}}}}',
    )
    sat, diags = rules.check_mcp_no_secrets(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_mcp_no_secrets_not_applicable_without_mcp(tmp_path):
    _write(tmp_path, "README.md", "# hello\n")
    assert rules.check_mcp_no_secrets(_index(tmp_path)) is None


# --- tooling.setup.script ----------------------------------------------------

def test_setup_script_satisfied(tmp_path):
    _write(tmp_path, "scripts/setup.sh", "#!/bin/sh\necho ok\n")
    sat, diags = rules.check_setup_script(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_setup_script_violated(tmp_path):
    _write(tmp_path, "README.md", "# hello\n")
    sat, diags = rules.check_setup_script(_index(tmp_path))
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


# --- tooling.devcontainer ----------------------------------------------------

def test_devcontainer_satisfied_by_fixture():
    sat, diags = rules.check_devcontainer(_index(FIXTURES / "repo_tooling_mcp"))
    assert sat == 1.0
    assert diags == []


def test_devcontainer_violated(tmp_path):
    _write(tmp_path, "README.md", "# hello\n")
    sat, diags = rules.check_devcontainer(_index(tmp_path))
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


# --- tooling.env.example -----------------------------------------------------

def test_env_example_satisfied(tmp_path):
    _write(tmp_path, ".gitignore", "node_modules/\n.env\n")
    _write(tmp_path, ".env.example", "API_KEY=\n")
    sat, diags = rules.check_env_example(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_env_example_violated(tmp_path):
    _write(tmp_path, ".gitignore", "node_modules/\n.env\n")
    sat, diags = rules.check_env_example(_index(tmp_path))
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


def test_env_example_not_applicable_without_env_ignore(tmp_path):
    _write(tmp_path, ".gitignore", "node_modules/\ndist/\n")
    assert rules.check_env_example(_index(tmp_path)) is None


def test_env_example_not_applicable_when_only_example_ignored(tmp_path):
    _write(tmp_path, ".gitignore", ".env.example\n")
    assert rules.check_env_example(_index(tmp_path)) is None


# --- tooling.versions.pinned -------------------------------------------------

def test_versions_pinned_satisfied_by_fixture():
    sat, diags = rules.check_versions_pinned(_index(FIXTURES / "repo_tooling_mcp"))
    assert sat == 1.0
    assert diags == []


def test_versions_pinned_violated(tmp_path):
    _write(tmp_path, "README.md", "# hello\n")
    sat, diags = rules.check_versions_pinned(_index(tmp_path))
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


# --- tooling.scripts.documented ----------------------------------------------

def test_scripts_documented_satisfied(tmp_path):
    _write(tmp_path, "package.json", _PKG_THREE_SCRIPTS)
    _write(
        tmp_path, "CLAUDE.md",
        "# Repo\n\nRun `npm run build` then `npm test` before committing.\n",
    )
    sat, diags = rules.check_scripts_documented(_index(tmp_path))
    assert sat == 1.0
    assert diags == []


def test_scripts_documented_violated_with_one_mention(tmp_path):
    _write(tmp_path, "package.json", _PKG_THREE_SCRIPTS)
    _write(tmp_path, "CLAUDE.md", "# Repo\n\nRun `npm run build` before committing.\n")
    sat, diags = rules.check_scripts_documented(_index(tmp_path))
    assert sat == 0.0
    assert diags[0].severity == Severity.WARNING


def test_scripts_documented_not_applicable_with_few_scripts(tmp_path):
    _write(tmp_path, "package.json", '{"scripts": {"build": "tsc", "test": "vitest"}}')
    _write(tmp_path, "CLAUDE.md", "Run `npm run build` and `npm test`.\n")
    assert rules.check_scripts_documented(_index(tmp_path)) is None


def test_scripts_documented_not_applicable_without_entrypoint(tmp_path):
    _write(tmp_path, "package.json", _PKG_THREE_SCRIPTS)
    assert rules.check_scripts_documented(_index(tmp_path)) is None
