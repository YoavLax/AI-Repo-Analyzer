"""Tests for the agents pillar rules (plan-v2-fable.md §4.5).

Each test builds a tiny repository (in tmp_path or from a committed fixture),
runs discovery, and calls the rule functions directly. The module is imported
explicitly because rules/__init__ wiring happens centrally later.
"""
from pathlib import Path, PurePosixPath

from airx import fs
from airx.discovery import build_index
from airx.model import Severity
from airx.rules import agents as rules  # direct import: not yet wired into airx.rules/__init__

FIXTURES = Path(__file__).parent / "fixtures"

GOOD_AGENT = """---
name: code-reviewer
description: >-
  Analyzes pull requests and diffs, checks style and correctness issues.
  Use this agent whenever the user asks to review code or validate a change.
tools: Read, Grep, Glob
---

Review the changed files and report findings ordered by severity.
"""


def _index(tmp_path: Path, files: dict[str, str]):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    tree = fs.scan(tmp_path)
    return build_index(tree)


def _fixture_index(name: str):
    tree = fs.scan(FIXTURES / name)
    return build_index(tree)


# =============================================================================
# agents.present / prompts.present
# =============================================================================

def test_agents_present_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_present(index)
    assert sat == 1.0
    assert diags == []


def test_agents_present_violated_when_no_agents(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    sat, diags = rules.check_agents_present(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


def test_prompts_present_satisfied(tmp_path):
    index = _index(tmp_path, {".github/prompts/deploy.prompt.md": "Deploy the app.\n"})
    sat, diags = rules.check_prompts_present(index)
    assert sat == 1.0
    assert diags == []


def test_prompts_present_violated_when_no_prompts():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_prompts_present(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


# =============================================================================
# agents.frontmatter.present
# =============================================================================

def test_frontmatter_present_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_frontmatter_present(index)
    assert sat == 1.0
    assert diags == []


def test_frontmatter_present_violated_by_broken_fixture():
    index = _fixture_index("repo_agents_broken")
    sat, diags = rules.check_agents_frontmatter_present(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/agents/helper.md")
    assert diag.severity == Severity.ERROR


def test_frontmatter_present_per_file_mean(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/good.md": GOOD_AGENT,
        ".claude/agents/naked.md": "No frontmatter here.\n",
    })
    sat, diags = rules.check_agents_frontmatter_present(index)
    assert sat == 0.5
    assert len(diags) == 1


def test_frontmatter_present_na_without_agents(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_agents_frontmatter_present(index) is None


# =============================================================================
# agents.name.required (Claude-side only)
# =============================================================================

def test_name_required_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_name_required(index)
    assert sat == 1.0
    assert diags == []


def test_name_required_violated_without_name(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/anon.md": "---\ndescription: Reviews code changes.\n---\n\nBody.\n",
    })
    sat, diags = rules.check_agents_name_required(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/agents/anon.md")
    assert diag.severity == Severity.ERROR


def test_name_required_na_for_github_agents_only(tmp_path):
    index = _index(tmp_path, {
        ".github/agents/fixer.md": "---\ndescription: Fixes reported bugs quickly.\n---\n\nBody.\n",
    })
    assert rules.check_agents_name_required(index) is None


# =============================================================================
# agents.description.required
# =============================================================================

def test_description_required_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_description_required(index)
    assert sat == 1.0
    assert diags == []


def test_description_required_violated_by_broken_fixture():
    index = _fixture_index("repo_agents_broken")
    sat, diags = rules.check_agents_description_required(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/agents/helper.md")
    assert diag.severity == Severity.ERROR


def test_description_required_na_without_agents(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_agents_description_required(index) is None


# =============================================================================
# agents.description.quality
# =============================================================================

def test_description_quality_good_beats_bad(tmp_path):
    good = _fixture_index("repo_agents_ok")
    bad = _index(tmp_path, {
        ".claude/agents/vague.md": "---\nname: vague\ndescription: Helps with stuff.\n---\n\nBody.\n",
    })
    good_sat, good_diags = rules.check_agents_description_quality(good)
    bad_sat, _ = rules.check_agents_description_quality(bad)
    assert good_sat > bad_sat
    rel, diag = good_diags[0]
    assert rel == PurePosixPath(".claude/agents/code-reviewer.md")
    assert diag.severity == Severity.INFO
    assert "/100" in diag.message


def test_description_quality_na_without_string_description(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/nodesc.md": "---\nname: nodesc\ntools: Read\n---\n\nBody.\n",
    })
    assert rules.check_agents_description_quality(index) is None


# =============================================================================
# agents.description.person-voice
# =============================================================================

def test_person_voice_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_description_person_voice(index)
    assert sat == 1.0
    assert diags == []


def test_person_voice_flags_first_person(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/me.md": "---\nname: me\ndescription: I can help you deploy things.\n---\n\nBody.\n",
    })
    sat, diags = rules.check_agents_description_person_voice(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/agents/me.md")
    assert diag.severity == Severity.WARNING


def test_person_voice_na_without_description(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/nodesc.md": "---\nname: nodesc\ntools: Read\n---\n\nBody.\n",
    })
    assert rules.check_agents_description_person_voice(index) is None


# =============================================================================
# agents.tools.declared
# =============================================================================

def test_tools_declared_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_tools_declared(index)
    assert sat == 1.0
    assert diags == []


def test_tools_declared_violated_without_tools(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/allpowerful.md": "---\nname: allpowerful\ndescription: Reviews code changes.\n---\n\nBody.\n",
    })
    sat, diags = rules.check_agents_tools_declared(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert diag.severity == Severity.WARNING


def test_tools_declared_na_without_agents(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_agents_tools_declared(index) is None


# =============================================================================
# agents.unknown-fields
# =============================================================================

def test_unknown_fields_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_unknown_fields(index)
    assert sat == 1.0
    assert diags == []


def test_unknown_fields_flags_stray_field(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/odd.md": (
            "---\nname: odd\ndescription: Reviews code changes.\ntools: Read\nfoo: bar\n---\n\nBody.\n"
        ),
    })
    sat, diags = rules.check_agents_unknown_fields(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert "foo" in diag.message
    assert diag.severity == Severity.WARNING


def test_unknown_fields_na_without_agents(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_agents_unknown_fields(index) is None


# --- v0.3.0 schema fix: current Claude subagent frontmatter fields -----------

def test_unknown_fields_accepts_current_claude_subagent_schema(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/researcher.md": (
            "---\nname: researcher\ndescription: Researches library docs when asked.\n"
            "tools: Read, Grep\ndisallowedTools: Bash\npermissionMode: plan\nmaxTurns: 10\n"
            "skills: [deploy]\nmcpServers: [context7]\nhooks: {}\nmemory: project\n"
            "background: false\neffort: high\nisolation: worktree\ninitialPrompt: Begin.\n"
            "---\n\nBody.\n"
        ),
    })
    sat, diags = rules.check_agents_unknown_fields(index)
    assert sat == 1.0
    assert diags == []


# =============================================================================
# agents.sizing
# =============================================================================

def test_sizing_satisfied_by_fixture():
    index = _fixture_index("repo_agents_ok")
    sat, diags = rules.check_agents_sizing(index)
    assert sat == 1.0
    assert diags == []


def test_sizing_violated_by_oversized_agent(tmp_path):
    body = "Line of text.\n" * 600
    index = _index(tmp_path, {
        ".claude/agents/huge.md": f"---\nname: huge\ndescription: Reviews code changes.\n---\n\n{body}",
    })
    sat, diags = rules.check_agents_sizing(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/agents/huge.md")
    assert "lines" in diag.message


def test_sizing_na_without_agents(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_agents_sizing(index) is None


# =============================================================================
# prompts.frontmatter.valid
# =============================================================================

def test_prompt_frontmatter_valid_with_resolving_agent(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/code-reviewer.md": GOOD_AGENT,
        ".github/prompts/review.prompt.md": (
            "---\nagent: code-reviewer\ndescription: Reviews the current diff.\n---\n\nReview my changes.\n"
        ),
    })
    sat, diags = rules.check_prompts_frontmatter_valid(index)
    assert sat == 1.0
    assert diags == []


def test_prompt_frontmatter_agent_resolves_by_filename_stem(tmp_path):
    index = _index(tmp_path, {
        ".github/agents/fixer.md": "---\ndescription: Fixes reported bugs quickly.\n---\n\nBody.\n",
        ".github/prompts/fix.prompt.md": "---\nagent: fixer\n---\n\nFix the bug.\n",
    })
    sat, diags = rules.check_prompts_frontmatter_valid(index)
    assert sat == 1.0
    assert diags == []


def test_prompt_without_frontmatter_passes(tmp_path):
    index = _index(tmp_path, {
        ".github/prompts/plain.prompt.md": "Just do the thing.\n",
    })
    sat, diags = rules.check_prompts_frontmatter_valid(index)
    assert sat == 1.0
    assert diags == []


def test_prompt_frontmatter_flags_dangling_agent_reference():
    index = _fixture_index("repo_agents_broken")
    sat, diags = rules.check_prompts_frontmatter_valid(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".github/prompts/fix.prompt.md")
    assert diag.severity == Severity.WARNING
    assert "ghost-agent" in diag.message


def test_prompt_frontmatter_flags_unknown_field(tmp_path):
    index = _index(tmp_path, {
        ".github/prompts/odd.prompt.md": "---\ntemperature: 0.2\n---\n\nDo it.\n",
    })
    sat, diags = rules.check_prompts_frontmatter_valid(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert "temperature" in diag.message


def test_prompt_frontmatter_na_without_prompts(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_prompts_frontmatter_valid(index) is None


# =============================================================================
# agents.commands.present / agents.commands.frontmatter.valid (v0.3.0)
# =============================================================================

def test_commands_present_satisfied(tmp_path):
    index = _index(tmp_path, {
        ".claude/commands/review.md": "---\ndescription: Reviews the diff.\n---\n\nReview it.\n",
    })
    sat, diags = rules.check_commands_present(index)
    assert sat == 1.0
    assert diags == []


def test_commands_present_violated_when_none(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    sat, diags = rules.check_commands_present(index)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


def test_commands_frontmatter_valid_accepts_current_schema(tmp_path):
    index = _index(tmp_path, {
        ".claude/commands/review.md": (
            "---\ndescription: Reviews the diff.\nwhen_to_use: When a PR is open.\n"
            "argument-hint: '[pr-number]'\ndisallowed-tools: Bash\neffort: high\n"
            "context: fork\nbackground: false\n---\n\nReview it.\n"
        ),
    })
    sat, diags = rules.check_commands_frontmatter_valid(index)
    assert sat == 1.0
    assert diags == []


def test_commands_frontmatter_valid_flags_unknown_field(tmp_path):
    index = _index(tmp_path, {
        ".claude/commands/odd.md": "---\ndescription: Does a thing.\nbogus-field: 1\n---\n\nBody.\n",
    })
    sat, diags = rules.check_commands_frontmatter_valid(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/commands/odd.md")
    assert "bogus-field" in diag.message


def test_commands_frontmatter_valid_flags_dangling_agent(tmp_path):
    index = _index(tmp_path, {
        ".claude/commands/odd.md": "---\ndescription: Does a thing.\nagent: ghost-agent\n---\n\nBody.\n",
    })
    sat, diags = rules.check_commands_frontmatter_valid(index)
    assert sat == 0.0
    assert "ghost-agent" in diags[0][1].message


def test_commands_frontmatter_valid_na_without_commands(tmp_path):
    index = _index(tmp_path, {"README.md": "# Hello\n"})
    assert rules.check_commands_frontmatter_valid(index) is None


# =============================================================================
# agents.mcp-servers.resolve (v0.3.0)
# =============================================================================

def test_mcp_servers_resolve_satisfied(tmp_path):
    index = _index(tmp_path, {
        ".mcp.json": '{"mcpServers": {"context7": {"command": "npx"}}}',
        ".claude/agents/researcher.md": (
            "---\nname: researcher\ndescription: Researches library docs when asked.\n"
            "mcpServers: [context7]\n---\n\nBody.\n"
        ),
    })
    sat, diags = rules.check_agents_mcp_servers_resolve(index)
    assert sat == 1.0
    assert diags == []


def test_mcp_servers_resolve_flags_unknown_server(tmp_path):
    index = _index(tmp_path, {
        ".mcp.json": '{"mcpServers": {"context7": {"command": "npx"}}}',
        ".claude/agents/researcher.md": (
            "---\nname: researcher\ndescription: Researches library docs when asked.\n"
            "mcpServers: [ghost-server]\n---\n\nBody.\n"
        ),
    })
    sat, diags = rules.check_agents_mcp_servers_resolve(index)
    assert sat == 0.0
    rel, diag = diags[0]
    assert rel == PurePosixPath(".claude/agents/researcher.md")
    assert "ghost-server" in diag.message


def test_mcp_servers_resolve_flags_unknown_server_without_any_mcp_config(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/researcher.md": (
            "---\nname: researcher\ndescription: Researches library docs when asked.\n"
            "mcp-servers: context7\n---\n\nBody.\n"
        ),
    })
    sat, diags = rules.check_agents_mcp_servers_resolve(index)
    assert sat == 0.0
    assert "context7" in diags[0][1].message


def test_mcp_servers_resolve_na_without_field(tmp_path):
    index = _index(tmp_path, {
        ".claude/agents/planner.md": GOOD_AGENT,
    })
    assert rules.check_agents_mcp_servers_resolve(index) is None
