"""Verification pillar: documented, resolvable feedback loops.

plan-v2-fable.md §4.6. An agent can only self-correct when the repository
tells it how to run the tests/build/lint, when that tooling actually exists
(RepoFacts), and when the instructions demand an iterate-until-green loop
with evidence. The command-mention scan collects inline-code spans and
fenced-block lines from the entry-point and instructions bodies; a command
is "documented" when a collected snippet contains a known command token or
resolves an actual package script / Makefile target from `RepoFacts`.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from airx.discovery import ArtifactIndex
from airx.model import (
    Applicability,
    Artifact,
    Diagnostic,
    ParsedDocument,
    Pillar,
    Platform,
    RuleSource,
    Severity,
)
from airx.rules.registry import RuleScope, rule

if TYPE_CHECKING:
    from airx.probe import RepoFacts

# --- snippet collection -------------------------------------------------------

_FENCED_BLOCK_RE = re.compile(r"^(?:```|~~~)[^\n]*\n(.*?)^(?:```|~~~)\s*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

# --- command tokens (plan-v2-fable.md §4.6) -----------------------------------

_TEST_COMMAND_TOKENS: tuple[str, ...] = (
    "pytest", "npm test", "go test", "cargo test", "dotnet test", "mvn test", "tox",
)
_BUILD_COMMAND_TOKENS: tuple[str, ...] = (
    "cargo build", "go build", "python -m build", "dotnet build",
)
_LINT_TOKENS: tuple[str, ...] = (
    "lint", "format", "fmt", "ruff", "eslint", "prettier", "flake8", "black",
)
_LINT_BARE_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(r"\b" + re.escape(tok) + r"\b") for tok in _LINT_TOKENS
)

# `npm run <s>` / `yarn <s>` / `pnpm <s>` script invocations and `make <t>`
# target invocations; the captured name is resolved against RepoFacts.
_SCRIPT_RUNNER_RE = re.compile(r"\b(?:npm\s+run|yarn(?:\s+run)?|pnpm(?:\s+run)?)\s+([A-Za-z0-9:_.-]+)")
_MAKE_TARGET_RE = re.compile(r"\bmake\s+([A-Za-z0-9_.-]+)")

# --- instruction phrase sets (plan-v2-fable.md §4.6 table) --------------------

_LOOP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"run the tests", re.IGNORECASE),
    re.compile(r"until (?:it|they) pass", re.IGNORECASE),
    re.compile(r"verify", re.IGNORECASE),
    re.compile(r"typecheck", re.IGNORECASE),
    re.compile(r"re-run", re.IGNORECASE),
    re.compile(r"iterate", re.IGNORECASE),
)

_EVIDENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"show the output", re.IGNORECASE),
    re.compile(r"paste the (?:test )?output", re.IGNORECASE),
    re.compile(r"include the command", re.IGNORECASE),
    re.compile(r"evidence", re.IGNORECASE),
)


def _command_docs(index: ArtifactIndex) -> list[ParsedDocument]:
    """Entry points followed by instructions files, in stable discovery order."""
    docs = list(index.entrypoint_docs())
    for artifact in index.instructions:
        if artifact.doc is not None:
            docs.append(artifact.doc)
    return docs


def _collect_snippets(index: ArtifactIndex) -> tuple[str, ...]:
    """Inline-code spans and fenced-block lines, lowercased, in document order."""
    snippets: list[str] = []
    for doc in _command_docs(index):
        body = doc.body
        for block in _FENCED_BLOCK_RE.findall(body):
            for line in block.splitlines():
                stripped = line.strip()
                if stripped:
                    snippets.append(stripped.lower())
        prose = _FENCED_BLOCK_RE.sub("", body)
        for span in _INLINE_CODE_RE.findall(prose):
            stripped = span.strip()
            if stripped:
                snippets.append(stripped.lower())
    return tuple(snippets)


def _script_names(snippet: str, facts: "RepoFacts") -> list[str]:
    """package.json script names invoked by the snippet (npm run/yarn/pnpm)."""
    known = tuple(s.lower() for s in facts.package_scripts)
    return [name for name in _SCRIPT_RUNNER_RE.findall(snippet) if name in known]


def _make_targets(snippet: str, facts: "RepoFacts") -> list[str]:
    """Makefile targets invoked by the snippet (`make <t>`)."""
    known = tuple(t.lower() for t in facts.makefile_targets)
    return [name for name in _MAKE_TARGET_RE.findall(snippet) if name in known]


def _documents_test_command(snippet: str, facts: "RepoFacts") -> bool:
    if any(tok in snippet for tok in _TEST_COMMAND_TOKENS):
        return True
    if _script_names(snippet, facts):
        return True
    return any("test" in target for target in _make_targets(snippet, facts))


def _documents_build_command(snippet: str, facts: "RepoFacts") -> bool:
    if any(tok in snippet for tok in _BUILD_COMMAND_TOKENS):
        return True
    if any("build" in name for name in _script_names(snippet, facts)):
        return True
    return any("build" in target for target in _make_targets(snippet, facts))


def _documents_lint_command(snippet: str, facts: "RepoFacts") -> bool:
    if any(pattern.search(snippet) for pattern in _LINT_BARE_RES):
        return True
    if any(any(tok in name for tok in _LINT_TOKENS) for name in _script_names(snippet, facts)):
        return True
    return any(
        any(tok in target for tok in _LINT_TOKENS) for target in _make_targets(snippet, facts)
    )


# --- rules -------------------------------------------------------------------


@rule(
    id="verify.test-command.documented", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=7, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/",
    summary="A test command is documented in the entry point or instructions files and resolves against the repository.",
    why="An agent can only self-verify a change when the docs state the exact test command and that command actually exists.",
    fix="Add the exact test command (e.g. `pytest` or `npm test`) to the entry point and make sure the test setup it names exists.",
    effort="additive",
)
def check_test_command_documented(index: ArtifactIndex):
    facts = index.facts
    documented = [s for s in _collect_snippets(index) if _documents_test_command(s, facts)]
    if not documented:
        return 0.0, [Diagnostic(
            rule_id="verify.test-command.documented", severity=Severity.WARNING,
            message="No test command is documented in the entry point or instructions files; "
                    "agents cannot self-verify changes without one.",
        )]
    if not facts.test_evidence:
        return 0.0, [Diagnostic(
            rule_id="verify.test-command.documented", severity=Severity.WARNING,
            message=f"A test command is documented (`{documented[0]}`) but does not resolve: "
                    f"no test suite evidence (pytest config, JS test config, tests/ directory, "
                    f"test script/target, or tox.ini) was found in the repository.",
        )]
    return 1.0, []


@rule(
    id="verify.build-command.documented", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=5, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/",
    summary="The repository's build command is documented in the entry point or instructions files.",
    why="A repository with a build system but no documented build command forces agents to guess how to compile their changes.",
    fix="Document the build command (e.g. `npm run build` or `cargo build`) in the entry point.",
    effort="additive",
)
def check_build_command_documented(index: ArtifactIndex):
    facts = index.facts
    if not facts.build_evidence:
        return None  # N/A: no build system detected
    if any(_documents_build_command(s, facts) for s in _collect_snippets(index)):
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.build-command.documented", severity=Severity.WARNING,
        message="The repository has a build system, but no build command is documented "
                "in the entry point or instructions files.",
    )]


@rule(
    id="verify.lint-command.documented", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/",
    summary="The repository's lint/format command is documented in the entry point or instructions files.",
    why="A configured linter that agents are never told to run produces style churn and review noise.",
    fix="Document the lint command (e.g. `make lint` or `ruff check .`) in the entry point.",
    effort="additive",
)
def check_lint_command_documented(index: ArtifactIndex):
    facts = index.facts
    if not facts.lint_evidence:
        return None  # N/A: no lint config detected
    if any(_documents_lint_command(s, facts) for s in _collect_snippets(index)):
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.lint-command.documented", severity=Severity.WARNING,
        message="The repository has lint configuration, but no lint command is documented "
                "in the entry point or instructions files.",
    )]


@rule(
    id="verify.test-suite.exists", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=5, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/memory#write-effective-instructions",
    summary="The repository has test suite evidence (test config, tests/ directory, or a test script).",
    why="Without a test suite there is no automated ground truth an agent can use to check its own work.",
    fix="Add a test suite (e.g. a tests/ directory with a pytest or JS test config) and a test script.",
    effort="authoring",
)
def check_test_suite_exists(index: ArtifactIndex):
    if index.facts.test_evidence:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.test-suite.exists", severity=Severity.WARNING,
        message="No test suite evidence found (no pytest/JS test config, tests/ directory, "
                "test script/target, or tox.ini).",
    )]


@rule(
    id="verify.ci.exists", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://docs.github.com/en/actions",
    summary="A CI workflow exists (GitHub Actions, GitLab CI, Azure Pipelines, or Jenkins).",
    why="CI is the independent verification layer that catches what an agent's local loop missed.",
    fix="Add a CI workflow (e.g. .github/workflows/ci.yml) that runs the test suite on every push.",
    effort="additive",
)
def check_ci_exists(index: ArtifactIndex):
    if index.facts.ci_workflows:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.ci.exists", severity=Severity.WARNING,
        message="No CI workflow found (.github/workflows/*.yml, .gitlab-ci.yml, "
                "azure-pipelines.yml, or Jenkinsfile).",
    )]


@rule(
    id="verify.loop.instructed", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/memory#write-effective-instructions",
    summary="The entry point instructs an iterate-until-green verification loop.",
    why="Agents follow explicit loops; without an instructed run-verify-iterate cycle they stop at the first plausible diff.",
    fix="Add a sentence like 'Run the tests after every change and iterate until they pass' to the entry point.",
    effort="additive",
)
def check_loop_instructed(index: ArtifactIndex):
    docs = index.entrypoint_docs()
    if not docs:
        return None  # N/A: no entry point to carry the instruction
    paths = index.entrypoint_paths()
    matched = sum(
        1 for pattern in _LOOP_PATTERNS if any(pattern.search(doc.body) for doc in docs)
    )
    if matched >= 2:
        return 1.0, []
    if matched == 1:
        return 0.5, [(path, Diagnostic(
            rule_id="verify.loop.instructed", severity=Severity.WARNING,
            message="The entry point hints at verification but does not instruct a full "
                    "iterate-until-green loop (only one verification cue found).",
        )) for path in paths]
    return 0.0, [(path, Diagnostic(
        rule_id="verify.loop.instructed", severity=Severity.WARNING,
        message="The entry point never instructs the agent to run the tests and iterate "
                "until they pass.",
    )) for path in paths]


@rule(
    id="verify.hooks.present", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/hooks",
    summary="Automated hooks are configured (.github/hooks/*.json or a hooks key in .claude/settings.json).",
    why="Hooks enforce verification mechanically instead of relying on the agent remembering an instruction.",
    fix="Add a hook configuration (.github/hooks/*.json or a `hooks` entry in .claude/settings.json) that runs checks automatically.",
    fix_by_platform=(
        (Platform.COPILOT, "Add a hook configuration (.github/hooks/*.json) that runs checks automatically."),
        (Platform.CLAUDE, "Add a `hooks` entry in .claude/settings.json that runs checks automatically."),
    ),
    effort="additive",
)
def check_hooks_present(index: ArtifactIndex):
    settings = index.claude_settings
    has_settings_hooks = (
        settings is not None
        and isinstance(settings.json_data, dict)
        and "hooks" in settings.json_data
    )
    if index.hooks or has_settings_hooks:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.hooks.present", severity=Severity.INFO,
        message="No automated hooks configured (.github/hooks/*.json or a `hooks` key in "
                ".claude/settings.json); verification relies on instructions alone.",
    )]


def _hook_file_problems(artifact: Artifact) -> list[str]:
    """Objective schema violations for one `.github/hooks/*.json` file."""
    if artifact.parse_error is not None:
        return [f"Hook file is not valid JSON: {artifact.parse_error}"]
    data = artifact.json_data
    if not isinstance(data, dict):
        return ["Hook file must be a JSON object."]
    problems: list[str] = []
    if data.get("version") != 1:
        problems.append("Hook file must declare `version: 1`.")
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        problems.append("Hook file must contain a `hooks` object.")
        return problems
    for event in sorted(hooks):
        value = hooks[event]
        entries = value if isinstance(value, list) else [value]
        for i, entry in enumerate(entries):
            label = f"{event}[{i}]" if isinstance(value, list) else event
            if not isinstance(entry, dict):
                problems.append(f"Hook entry `{label}` must be an object.")
                continue
            if entry.get("type") != "command":
                problems.append(f"Hook entry `{label}` must have `type: \"command\"`.")
            if "bash" not in entry and "powershell" not in entry:
                problems.append(f"Hook entry `{label}` must define a `bash` or `powershell` command.")
    return problems


@rule(
    id="verify.hooks.schema", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC, platforms=(Platform.COPILOT,),
    doc_url="https://code.visualstudio.com/docs/copilot/customization/hooks",
    summary="Every .github/hooks/*.json file is valid JSON matching the hooks schema (version 1, command entries).",
    why="A malformed hook file is silently ignored, so the verification it was meant to enforce never runs.",
    fix="Make each .github/hooks/*.json declare `version: 1` and a `hooks` object whose entries have `type: \"command\"` and a `bash` or `powershell` command.",
    effort="mechanical",
    spec_quote="Create a JSON file with a `hooks` object containing arrays of hook commands for each event type.",
)
def check_hooks_schema(index: ArtifactIndex):
    # Contents rule: only hook files whose bytes are in this snapshot.
    hooks = index.analyzed(index.hooks)
    if not hooks:
        return None  # N/A: no hook files
    sats: list[float] = []
    diags: list[tuple] = []
    for artifact in hooks:  # already sorted by rel_path
        problems = _hook_file_problems(artifact)
        if problems:
            sats.append(0.0)
            for message in problems:
                diags.append((artifact.rel_path, Diagnostic(
                    rule_id="verify.hooks.schema", severity=Severity.ERROR, message=message,
                )))
        else:
            sats.append(1.0)
    return (sum(sats) / len(sats)), diags


@rule(
    id="verify.evidence.instructed", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/memory#write-effective-instructions",
    summary="The entry point asks the agent to show evidence (command output) for its claims.",
    why="Requiring pasted command output turns 'it works' claims into checkable facts.",
    fix="Add a sentence like 'When you claim a fix works, show the output of the test run' to the entry point.",
    effort="additive",
)
def check_evidence_instructed(index: ArtifactIndex):
    docs = index.entrypoint_docs()
    if not docs:
        return None  # N/A: no entry point to carry the instruction
    if any(pattern.search(doc.body) for doc in docs for pattern in _EVIDENCE_PATTERNS):
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.evidence.instructed", severity=Severity.INFO,
        message="The entry point never asks the agent to show command output as evidence "
                "for its claims.",
    )]


# =============================================================================
# verify.hooks.enforces-lint (v0.3.0)
# =============================================================================

def _iter_strings(node) -> "list[str]":
    """Every string leaf in a JSON-like structure, walked in a stable order."""
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for key in sorted(node, key=str):
            out.extend(_iter_strings(node[key]))
    elif isinstance(node, list):
        for item in node:
            out.extend(_iter_strings(item))
    return out


@rule(
    id="verify.hooks.enforces-lint", pillar=Pillar.VERIFICATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://www.humanlayer.dev/blog/writing-a-good-claude-md",
    summary="At least one configured hook runs a lint/format command, instead of relying on "
            "written instructions alone.",
    why="Claude is not an expensive linter: a hook that runs the formatter and surfaces errors "
        "enforces style mechanically, without spending agent turns or context on style review.",
    fix="Add a PostToolUse or Stop hook (.github/hooks/*.json, or the `hooks` key in "
        ".claude/settings.json) that runs the project's lint/format command.",
    effort="additive",
)
def check_hooks_enforces_lint(index: ArtifactIndex):
    settings = index.claude_settings
    settings_hooks = (
        settings.json_data.get("hooks")
        if settings is not None and isinstance(settings.json_data, dict)
        else None
    )
    # Contents rule: hook files this snapshot never read contribute no strings,
    # so counting them here would report "no lint command" without evidence.
    hooks = index.analyzed(index.hooks)
    if not hooks and not settings_hooks:
        return None  # N/A: no hooks configured at all (verify.hooks.present covers that gap)
    strings: list[str] = []
    for artifact in hooks:
        if isinstance(artifact.json_data, dict):
            strings.extend(_iter_strings(artifact.json_data.get("hooks")))
    if settings_hooks is not None:
        strings.extend(_iter_strings(settings_hooks))
    lowered = [s.lower() for s in strings]
    if any(any(tok in s for tok in _LINT_TOKENS) for s in lowered):
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="verify.hooks.enforces-lint", severity=Severity.INFO,
        message="Hooks are configured but none of them runs a lint/format command; style "
                "review is left to the agent instead of being enforced mechanically.",
    )]
