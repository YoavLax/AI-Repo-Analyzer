"""Discovery classification tests for the full v0.2.0 artifact model."""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import ArtifactKind, Platform


def _write(root: Path, rel: str, content: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _index(root: Path):
    return build_index(fs.scan(root))


def test_full_artifact_model_is_classified(tmp_path: Path) -> None:
    _write(tmp_path, ".github/copilot-instructions.md", "# Copilot\n\nRules here.\n")
    _write(tmp_path, "CLAUDE.md", "# Claude\n\nRules here.\n")
    _write(tmp_path, "CLAUDE.local.md", "personal\n")
    _write(tmp_path, "AGENTS.md", "# Agents\n")
    _write(tmp_path, "packages/api/AGENTS.md", "# Nested\n")
    _write(tmp_path, ".github/instructions/py.instructions.md", "---\napplyTo: '**/*.py'\n---\nUse ruff.\n")
    _write(tmp_path, ".github/prompts/fix.prompt.md", "---\nmode: agent\n---\nFix it.\n")
    _write(tmp_path, ".github/agents/reviewer.md", "---\nname: reviewer\ndescription: Reviews diffs when asked.\n---\nBody.\n")
    _write(tmp_path, ".claude/agents/planner.md", "---\nname: planner\ndescription: Plans work when asked.\n---\nBody.\n")
    _write(tmp_path, ".claude/rules/style.md", "---\npaths: ['src/**']\n---\nStyle.\n")
    _write(tmp_path, ".github/hooks/format.json", '{"version": 1, "hooks": {}}')
    _write(tmp_path, ".mcp.json", '{"mcpServers": {}}')
    _write(tmp_path, ".claude/settings.json", '{"permissions": {}}')
    _write(tmp_path, ".claude/settings.local.json", "{}")
    _write(tmp_path, ".claude/skills/deploy/SKILL.md", "---\nname: deploy\ndescription: Deploys when asked.\n---\nBody.\n")
    _write(tmp_path, "src/app.py", "print()\n")

    index = _index(tmp_path)

    assert index.copilot_instructions is not None
    assert index.claude_md is not None
    assert index.claude_md_path == PurePosixPath("CLAUDE.md")
    assert index.claude_local_md_paths == (PurePosixPath("CLAUDE.local.md"),)
    assert index.agents_md_paths == (
        PurePosixPath("AGENTS.md"), PurePosixPath("packages/api/AGENTS.md"),
    )
    assert index.agents_md_nested == (PurePosixPath("packages/api/AGENTS.md"),)
    assert [str(a.rel_path) for a in index.instructions] == [".github/instructions/py.instructions.md"]
    assert [str(a.rel_path) for a in index.prompts] == [".github/prompts/fix.prompt.md"]
    assert [str(a.rel_path) for a in index.agents] == [
        ".claude/agents/planner.md", ".github/agents/reviewer.md",
    ]
    assert index.agents[0].platform == Platform.CLAUDE
    assert index.agents[1].platform == Platform.COPILOT
    assert [str(a.rel_path) for a in index.claude_rules] == [".claude/rules/style.md"]
    assert [str(a.rel_path) for a in index.hooks] == [".github/hooks/format.json"]
    assert index.hooks[0].json_data == {"version": 1, "hooks": {}}
    assert [str(a.rel_path) for a in index.mcp] == [".mcp.json"]
    assert index.claude_settings is not None
    assert index.claude_settings.json_data == {"permissions": {}}
    assert index.claude_settings_local_paths == (PurePosixPath(".claude/settings.local.json"),)
    assert len(index.skills) == 1
    assert index.facts is not None
    assert index.tree is not None
    # Plain source files are not artifacts.
    assert all(str(a.rel_path) != "src/app.py" for a in index.artifacts)


def test_malformed_json_artifact_records_parse_error(tmp_path: Path) -> None:
    _write(tmp_path, ".mcp.json", "{not json")
    index = _index(tmp_path)
    assert index.mcp[0].json_data is None
    assert index.mcp[0].parse_error is not None


def test_root_claude_md_preferred_over_dot_claude(tmp_path: Path) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "# dot\n")
    _write(tmp_path, "CLAUDE.md", "# root\n")
    index = _index(tmp_path)
    assert index.claude_md_path == PurePosixPath("CLAUDE.md")
    assert "root" in index.claude_md.raw_text


def test_skill_discovered_in_all_three_roots(tmp_path: Path) -> None:
    for root in (".github/skills", ".claude/skills", ".agents/skills"):
        _write(tmp_path, f"{root}/demo/SKILL.md", "---\nname: demo\ndescription: Does a demo when asked.\n---\nBody.\n")
    index = _index(tmp_path)
    assert len(index.skills) == 3
