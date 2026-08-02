"""Agents pillar: custom agent files and reusable prompt files
(plan-v2-fable.md §4.5).

Covers `.github/agents/**/*.md`, `.claude/agents/**/*.md`, and
`.github/prompts/**/*.prompt.md`. All rules here are REPO-scope: agent and
prompt artifacts are discovered as `Artifact`s on the `ArtifactIndex` (not as
skill documents), so each rule iterates the relevant artifact tuple in sorted
order, evaluates per file, aggregates by mean, and attaches per-file
`(rel_path, Diagnostic)` findings. Every rule is N/A when no agent
(respectively prompt) files exist.

Description scoring and person-voice detection are deliberately shared with
the skills pillar: `score_description` and the first/second-person regexes are
reused from `airx.rules.skills` so both pillars grade text identically.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from airx import config
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Artifact, Diagnostic, Pillar, Platform, RuleSource, Severity
from airx.rules import skills as skills_rules
from airx.rules.registry import RuleScope, rule
from airx.rules.skills import score_description
from airx.tokenizer import estimate_tokens

_DOC_URL_CLAUDE_AGENTS = "https://code.claude.com/docs/en/sub-agents"
_DOC_URL_COPILOT_AGENTS = "https://code.visualstudio.com/docs/copilot/customization/custom-agents"
_DOC_URL_PROMPTS = "https://code.visualstudio.com/docs/copilot/customization/prompt-files"

#: One diagnostic per file, keyed by repo-relative path (scoring normalizes
#: these tuples into path-annotated findings).
FileDiag = tuple[PurePosixPath, Diagnostic]


def _sorted_artifacts(artifacts: tuple[Artifact, ...]) -> list[Artifact]:
    return sorted(artifacts, key=lambda a: a.rel_path.as_posix())


def _agent_docs(index: ArtifactIndex) -> list[Artifact]:
    """Agent artifacts that parsed successfully, in sorted path order."""
    return [a for a in _sorted_artifacts(index.agents) if a.doc is not None]


def _mean(sats: list[float]) -> float:
    return sum(sats) / len(sats)


def _description_of(artifact: Artifact) -> str | None:
    desc = artifact.doc.frontmatter.get("description") if artifact.doc else None
    if isinstance(desc, str) and desc.strip():
        return desc
    return None


# =============================================================================
# presence
# =============================================================================

@rule(
    id="agents.present", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=5, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_CLAUDE_AGENTS,
    summary="At least one custom agent file exists (.github/agents/ or .claude/agents/).",
    why="Custom agents give recurring tasks a scoped persona with its own tools and instructions instead of re-prompting from scratch.",
    fix="Add an agent Markdown file under .claude/agents/ or .github/agents/ with name, description, and tools frontmatter.",
    fix_by_platform=(
        (Platform.COPILOT, "Add an agent Markdown file under .github/agents/ with name, description, "
                           "and tools frontmatter."),
        (Platform.CLAUDE, "Add an agent Markdown file under .claude/agents/ with name, description, "
                          "and tools frontmatter."),
    ),
    effort="authoring",
)
def check_agents_present(index: ArtifactIndex):
    if index.agents:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="agents.present", severity=Severity.INFO,
        message="No custom agent files found (.github/agents/**/*.md or .claude/agents/**/*.md).",
    )]


@rule(
    id="prompts.present", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_PROMPTS,
    platforms=(Platform.COPILOT,),
    why="Reusable prompt files turn common workflows into one-command invocations shared by the whole team.",
    fix="Add a *.prompt.md file under .github/prompts/ for a recurring task.",
    effort="authoring",
    summary="At least one reusable prompt file exists (.github/prompts/**/*.prompt.md).",
)
def check_prompts_present(index: ArtifactIndex):
    if index.prompts:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="prompts.present", severity=Severity.INFO,
        message="No reusable prompt files found (.github/prompts/**/*.prompt.md).",
    )]


# =============================================================================
# agent frontmatter
# =============================================================================

@rule(
    id="agents.frontmatter.present", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url=_DOC_URL_CLAUDE_AGENTS,
    why="An agent file without frontmatter has no name, description, or tool scope, so the platform cannot route to it.",
    fix="Add a YAML frontmatter block (---) with at least name and description to each agent file.",
    effort="additive",
    summary="Every agent file has non-empty YAML frontmatter.",
)
def check_agents_frontmatter_present(index: ArtifactIndex):
    agents = _sorted_artifacts(index.agents)
    if not agents:
        return None
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a in agents:
        if a.doc is None:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.frontmatter.present", severity=Severity.ERROR,
                message=f"Agent file failed to parse: {a.parse_error}",
            )))
        elif not a.doc.frontmatter:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.frontmatter.present", severity=Severity.ERROR,
                message="Agent file has no YAML frontmatter; add a --- block with name, description, and tools.",
            )))
        else:
            sats.append(1.0)
    return _mean(sats), diags


@rule(
    id="agents.name.required", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url=_DOC_URL_CLAUDE_AGENTS,
    platforms=(Platform.CLAUDE,),
    why="Claude Code identifies a subagent by its frontmatter name; without it the agent cannot be invoked.",
    fix="Add a non-empty `name:` field to each .claude/agents/*.md frontmatter.",
    effort="mechanical",
    summary="Every .claude/agents/ file declares a non-empty string `name`.",
)
def check_agents_name_required(index: ArtifactIndex):
    claude_agents = [
        a for a in _agent_docs(index) if a.platform == Platform.CLAUDE
    ]
    if not claude_agents:
        return None  # N/A: .github/agents files use the filename as the name.
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a in claude_agents:
        name = a.doc.frontmatter.get("name")
        if isinstance(name, str) and name.strip():
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.name.required", severity=Severity.ERROR,
                message="Claude agent file is missing a non-empty string `name` in frontmatter.",
            )))
    return _mean(sats), diags


@rule(
    id="agents.description.required", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url=_DOC_URL_CLAUDE_AGENTS,
    why="The description is what the platform matches against to decide when to delegate to the agent.",
    fix="Add a non-empty `description:` field describing what the agent does and when to use it.",
    effort="authoring",
    summary="Every agent file declares a non-empty string `description`.",
)
def check_agents_description_required(index: ArtifactIndex):
    agents = _agent_docs(index)
    if not agents:
        return None
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a in agents:
        desc = a.doc.frontmatter.get("description")
        if isinstance(desc, str) and desc.strip():
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.description.required", severity=Severity.ERROR,
                message="Agent file is missing a non-empty string `description` in frontmatter.",
            )))
    return _mean(sats), diags


@rule(
    id="agents.description.quality", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    why="A specific, trigger-rich description determines whether the platform ever delegates work to the agent.",
    fix="Rewrite the description with action verbs, trigger phrases, and domain keywords (mirror a well-scored SKILL.md description).",
    effort="authoring",
    summary="Graded 0-100 score of agent description discoverability (shared with the skills scorer).",
)
def check_agents_description_quality(index: ArtifactIndex):
    scored = [(a, _description_of(a)) for a in _agent_docs(index)]
    scored = [(a, d) for a, d in scored if d is not None]
    if not scored:
        return None  # N/A: missing descriptions are agents.description.required's finding.
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a, desc in scored:
        score, suggestions = score_description(desc)
        sats.append(score / 100.0)
        suffix = " Suggestions: " + "; ".join(suggestions) if suggestions else ""
        diags.append((a.rel_path, Diagnostic(
            rule_id="agents.description.quality", severity=Severity.INFO,
            message=f"Description quality score: {score}/100.{suffix}",
        )))
    return _mean(sats), diags


@rule(
    id="agents.description.person-voice", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    why="Third-person descriptions route better because the model reads them as capability statements, not dialogue.",
    fix="Rewrite the description in third person, e.g. 'Reviews...' instead of 'I review...' or 'You can...'.",
    effort="mechanical",
    summary="Agent descriptions are written in third person, not first/second person.",
)
def check_agents_description_person_voice(index: ArtifactIndex):
    scored = [(a, _description_of(a)) for a in _agent_docs(index)]
    scored = [(a, d) for a, d in scored if d is not None]
    if not scored:
        return None
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a, desc in scored:
        m = skills_rules._FIRST_PERSON_RE.search(desc)
        voice = "first"
        if m is None:
            m = skills_rules._SECOND_PERSON_RE.search(desc)
            voice = "second"
        if m is None:
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.description.person-voice", severity=Severity.WARNING,
                message=f"Agent description uses {voice}-person voice ('{m.group().strip()}'). "
                        f"Use third person, e.g. 'Reviews...' or 'Generates...'.",
            )))
    return _mean(sats), diags


@rule(
    id="agents.tools.declared", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_CLAUDE_AGENTS,
    why="An agent without a `tools` declaration inherits every tool; least privilege limits blast radius and sharpens behavior.",
    fix="Declare an explicit `tools:` list with only the tools the agent needs.",
    effort="additive",
    summary="Every agent file declares a `tools` field (least privilege over inherit-everything).",
)
def check_agents_tools_declared(index: ArtifactIndex):
    agents = _agent_docs(index)
    if not agents:
        return None
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a in agents:
        if "tools" in a.doc.frontmatter:
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.tools.declared", severity=Severity.WARNING,
                message="Agent file declares no `tools` field, so it inherits every available tool.",
            )))
    return _mean(sats), diags


@rule(
    id="agents.unknown-fields", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_COPILOT_AGENTS,
    why="Unknown frontmatter fields are silently ignored by the platforms, hiding typos of real fields.",
    fix="Remove or rename frontmatter fields outside the known agent schema.",
    effort="mechanical",
    summary="Agent frontmatter has no fields outside the known agent schema.",
)
def check_agents_unknown_fields(index: ArtifactIndex):
    agents = _agent_docs(index)
    if not agents:
        return None
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a in agents:
        unknown = sorted(str(f) for f in a.doc.frontmatter if str(f) not in config.KNOWN_AGENT_FIELDS)
        if not unknown:
            sats.append(1.0)
        else:
            sats.append(0.0)
            for field in unknown:
                diags.append((a.rel_path, Diagnostic(
                    rule_id="agents.unknown-fields", severity=Severity.WARNING,
                    message=f"Unknown agent frontmatter field '{field}'.",
                )))
    return _mean(sats), diags


@rule(
    id="agents.sizing", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url=_DOC_URL_CLAUDE_AGENTS,
    why="Oversized agent files consume context on every delegation and dilute the instructions that matter.",
    fix="Trim the agent file below 500 lines / ~8,000 tokens; move reference material elsewhere.",
    effort="authoring",
    summary=f"Every agent file is at most {config.AGENT_MAX_LINES} lines and ~{config.AGENT_MAX_TOKENS} tokens.",
)
def check_agents_sizing(index: ArtifactIndex):
    agents = _agent_docs(index)
    if not agents:
        return None
    sats: list[float] = []
    diags: list[FileDiag] = []
    for a in agents:
        lines = a.doc.line_count
        tokens = estimate_tokens(a.doc.raw_text)
        issues: list[str] = []
        if lines > config.AGENT_MAX_LINES:
            issues.append(f"{lines} lines (limit {config.AGENT_MAX_LINES})")
        if tokens > config.AGENT_MAX_TOKENS:
            issues.append(f"~{tokens} tokens (limit {config.AGENT_MAX_TOKENS})")
        if not issues:
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="agents.sizing", severity=Severity.WARNING,
                message=f"Agent file is oversized: {'; '.join(issues)}.",
            )))
    return _mean(sats), diags


# =============================================================================
# prompt frontmatter
# =============================================================================

def _known_agent_names(index: ArtifactIndex) -> frozenset[str]:
    """Names a prompt's `agent:` field can legitimately reference: each agent
    file's filename stem plus its frontmatter `name` when it is a string."""
    names: set[str] = set()
    for a in _sorted_artifacts(index.agents):
        names.add(a.rel_path.stem)
        if a.doc is not None:
            name = a.doc.frontmatter.get("name")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
    return frozenset(names)


@rule(
    id="prompts.frontmatter.valid", pillar=Pillar.AGENTS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url=_DOC_URL_PROMPTS,
    platforms=(Platform.COPILOT,),
    why="Unknown prompt fields are ignored and a dangling agent reference makes the prompt silently fall back to the default agent.",
    fix="Keep prompt frontmatter within the known field set and point `agent:` at an existing agent file's name or filename stem.",
    effort="mechanical",
    summary="Prompt frontmatter uses only known fields, and any `agent:` reference resolves to an existing agent.",
)
def check_prompts_frontmatter_valid(index: ArtifactIndex):
    prompts = [a for a in _sorted_artifacts(index.prompts) if a.doc is not None]
    if not prompts:
        return None
    agent_names = _known_agent_names(index)
    sats: list[float] = []
    diags: list[FileDiag] = []
    for p in prompts:
        fm = p.doc.frontmatter
        file_diags: list[Diagnostic] = []
        if fm:  # a prompt with no frontmatter passes: nothing to validate.
            for field in sorted(str(f) for f in fm if str(f) not in config.KNOWN_PROMPT_FIELDS):
                file_diags.append(Diagnostic(
                    rule_id="prompts.frontmatter.valid", severity=Severity.WARNING,
                    message=f"Unknown prompt frontmatter field '{field}'.",
                ))
            agent_ref = fm.get("agent")
            if isinstance(agent_ref, str) and agent_ref.strip() and agent_ref.strip() not in agent_names:
                file_diags.append(Diagnostic(
                    rule_id="prompts.frontmatter.valid", severity=Severity.WARNING,
                    message=f"Prompt references agent '{agent_ref.strip()}' but no agent file with that "
                            f"frontmatter name or filename stem exists.",
                ))
        sats.append(1.0 if not file_diags else 0.0)
        diags.extend((p.rel_path, d) for d in file_diags)
    return _mean(sats), diags
