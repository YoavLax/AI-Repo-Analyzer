"""Declarative artifact-discovery patterns (plan.md §5.1, plan-v2-fable.md §3.2).

Each pattern is a `(kind, platform, matcher)` triple where `matcher` is a small
pure predicate over a repo-relative `PurePosixPath`. Discovery walks the sorted
file list once and classifies each file with the first matching pattern, so the
order below is the precedence order.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Callable, NamedTuple

from airx.model import ArtifactKind, Platform

Matcher = Callable[[PurePosixPath], bool]


class PatternSpec(NamedTuple):
    kind: ArtifactKind
    platform: Platform
    matcher: Matcher


def _is_skill_file(rel: PurePosixPath) -> bool:
    # `**/skills/<name>/SKILL.md` — the skills directory must be the immediate
    # grandparent. Superset of `.github/skills`, `.claude/skills`, `.agents/skills`.
    if rel.name != "SKILL.md":
        return False
    parts = rel.parts
    return len(parts) >= 3 and parts[-3] == "skills"


def _is_instructions_file(rel: PurePosixPath) -> bool:
    return (
        rel.name.endswith(".instructions.md")
        and len(rel.parts) >= 3
        and rel.parts[0] == ".github"
        and rel.parts[1] == "instructions"
    )


def _is_prompt_file(rel: PurePosixPath) -> bool:
    return (
        rel.name.endswith(".prompt.md")
        and len(rel.parts) >= 3
        and rel.parts[0] == ".github"
        and rel.parts[1] == "prompts"
    )


#: Markdown files that live in an agents directory but are documentation about
#: the agents rather than agent definitions. Claude Code would fail to load
#: them, but "add name and description frontmatter to your README" is advice no
#: maintainer should take, and an ERROR is what we would be giving it.
_AGENT_DIR_DOC_FILENAMES: frozenset[str] = frozenset({"README.md", "readme.md"})


def _is_agent_file(rel: PurePosixPath) -> bool:
    if rel.suffix != ".md" or len(rel.parts) < 3:
        return False
    if rel.name in _AGENT_DIR_DOC_FILENAMES:
        return False
    return (rel.parts[0] == ".github" and rel.parts[1] == "agents") or (
        rel.parts[0] == ".claude" and rel.parts[1] == "agents"
    )


def _is_command_file(rel: PurePosixPath) -> bool:
    # `.claude/commands/**/*.md` — reusable Claude Code custom slash commands
    # (claude-commands.md). No GitHub Copilot equivalent exists today; prompt
    # files (`.github/prompts/**/*.prompt.md`) already cover that role.
    return (
        rel.suffix == ".md"
        and len(rel.parts) >= 3
        and rel.parts[0] == ".claude"
        and rel.parts[1] == "commands"
    )


def _is_claude_rule(rel: PurePosixPath) -> bool:
    return (
        rel.suffix == ".md"
        and len(rel.parts) >= 3
        and rel.parts[0] == ".claude"
        and rel.parts[1] == "rules"
    )


def _is_hooks_file(rel: PurePosixPath) -> bool:
    return (
        rel.suffix == ".json"
        and len(rel.parts) == 3
        and rel.parts[0] == ".github"
        and rel.parts[1] == "hooks"
    )


_MCP_PATHS = (
    PurePosixPath(".mcp.json"),
    PurePosixPath(".vscode/mcp.json"),
    PurePosixPath("mcp.json"),
)

_SETUP_STEPS_PATHS = (
    PurePosixPath(".github/workflows/copilot-setup-steps.yml"),
    PurePosixPath(".github/workflows/copilot-setup-steps.yaml"),
)


def _agent_platform(rel: PurePosixPath) -> Platform:
    return Platform.COPILOT if rel.parts[0] == ".github" else Platform.CLAUDE


DISCOVERY_PATTERNS: tuple[PatternSpec, ...] = (
    PatternSpec(ArtifactKind.SKILL, Platform.NEUTRAL, _is_skill_file),
    PatternSpec(
        ArtifactKind.ENTRYPOINT_COPILOT,
        Platform.COPILOT,
        lambda rel: rel == PurePosixPath(".github/copilot-instructions.md"),
    ),
    PatternSpec(
        ArtifactKind.ENTRYPOINT_CLAUDE,
        Platform.CLAUDE,
        lambda rel: rel in (PurePosixPath("CLAUDE.md"), PurePosixPath(".claude/CLAUDE.md")),
    ),
    PatternSpec(
        ArtifactKind.ENTRYPOINT_GEMINI,
        # GitHub Copilot coding agent reads a root GEMINI.md in addition to
        # .github/copilot-instructions.md, AGENTS.md and CLAUDE.md. The exact
        # claim relied on, from GitHub's "add repository instructions" docs:
        #
        #   "Copilot coding agent [...] also supports AGENTS.md, CLAUDE.md and
        #    GEMINI.md files."
        #
        # This is what makes `foundation.copilot.entrypoint` satisfiable by a
        # GEMINI.md alone. If GitHub ever drops GEMINI.md from that list, this
        # spec and that rule are what have to change — nothing else depends on
        # the claim. This analyzer models only the Copilot/Claude platform axis,
        # so GEMINI.md is an additional Copilot-visible entry point rather than
        # a third platform.
        # https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions
        Platform.COPILOT,
        lambda rel: rel == PurePosixPath("GEMINI.md"),
    ),
    PatternSpec(
        ArtifactKind.CLAUDE_LOCAL_MD,
        Platform.CLAUDE,
        lambda rel: rel == PurePosixPath("CLAUDE.local.md"),
    ),
    PatternSpec(ArtifactKind.AGENTS_MD, Platform.NEUTRAL, lambda rel: rel.name == "AGENTS.md"),
    PatternSpec(ArtifactKind.INSTRUCTIONS, Platform.COPILOT, _is_instructions_file),
    PatternSpec(ArtifactKind.PROMPT, Platform.COPILOT, _is_prompt_file),
    PatternSpec(ArtifactKind.AGENT, Platform.NEUTRAL, _is_agent_file),  # platform refined below
    PatternSpec(ArtifactKind.COMMAND, Platform.CLAUDE, _is_command_file),
    PatternSpec(ArtifactKind.CLAUDE_RULE, Platform.CLAUDE, _is_claude_rule),
    PatternSpec(ArtifactKind.HOOKS, Platform.COPILOT, _is_hooks_file),
    PatternSpec(ArtifactKind.MCP, Platform.NEUTRAL, lambda rel: rel in _MCP_PATHS),
    PatternSpec(
        ArtifactKind.CLAUDE_SETTINGS,
        Platform.CLAUDE,
        lambda rel: rel == PurePosixPath(".claude/settings.json"),
    ),
    PatternSpec(
        ArtifactKind.CLAUDE_SETTINGS_LOCAL,
        Platform.CLAUDE,
        lambda rel: rel == PurePosixPath(".claude/settings.local.json"),
    ),
    PatternSpec(ArtifactKind.SETUP_STEPS, Platform.COPILOT, lambda rel: rel in _SETUP_STEPS_PATHS),
)


def classify(rel: PurePosixPath) -> tuple[ArtifactKind, Platform] | None:
    """Return the artifact kind and platform for a path, or None for plain files."""
    for spec in DISCOVERY_PATTERNS:
        if spec.matcher(rel):
            if spec.kind == ArtifactKind.AGENT:
                return spec.kind, _agent_platform(rel)
            return spec.kind, spec.platform
    return None
