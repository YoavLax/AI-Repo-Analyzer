"""Safety pillar: committed personal files, permission bypass, settings
hygiene, secret shapes in settings, and the remote-script injection surface
(plan-v2-fable.md §4.8).

All six rules are pure functions over the `ArtifactIndex`. Two advisory rules
(`safety.permissions.no-bypass`, `safety.settings.no-secrets`) carry ERROR
severity via the registry allowlist because their checks are objective config
values / credential shapes, not stylistic heuristics.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import Any

from airx import config
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, Pillar, Platform, RuleSource, Severity
from airx.rules.registry import RuleScope, rule

_CLAUDE_ONLY: tuple[Platform, ...] = (Platform.CLAUDE,)

#: Compiled credential shapes (config.SECRET_SHAPE_PATTERNS, plan.md §13).
_SECRET_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in config.SECRET_SHAPE_PATTERNS
)

#: Remote-script-piped-to-shell shapes (plan-v2-fable.md §4.8, injection surface).
#: Case-insensitive per the §4 legend (all text matching is case-insensitive).
_INJECTION_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("curl-pipe-shell", re.compile(r"curl[^\n]*\|\s*(?:ba|z)?sh", re.IGNORECASE)),
    ("wget-pipe-shell", re.compile(r"wget[^\n]*\|\s*(?:ba|z)?sh", re.IGNORECASE)),
    ("iwr-pipe-iex", re.compile(r"(?:iwr|Invoke-WebRequest)[^\n]*\|\s*iex", re.IGNORECASE)),
)

_BYPASS_VALUE = "bypassPermissions"
_BYPASS_KEY = "dangerouslySkipPermissions"


@rule(
    id="safety.local-files.not-committed", pillar=Pillar.SAFETY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
    source=RuleSource.SPEC,
    doc_url="https://code.claude.com/docs/en/settings#settings-files",
    summary="Personal Claude files (CLAUDE.local.md, .claude/settings.local.json) are not committed.",
    platforms=_CLAUDE_ONLY,
    why="Local settings files are personal, machine-specific configuration; committing them leaks local setup into every clone.",
    fix="Remove CLAUDE.local.md / .claude/settings.local.json from version control and add them to .gitignore.",
    effort="mechanical",
)
def check_local_files_not_committed(index: ArtifactIndex):
    """Always applicable: passes trivially when no local file is in the tree."""
    local_paths = sorted(
        tuple(index.claude_settings_local_paths) + tuple(index.claude_local_md_paths),
        key=lambda p: p.as_posix(),
    )
    if not local_paths:
        return 1.0, []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for path in local_paths:
        diags.append((path, Diagnostic(
            rule_id="safety.local-files.not-committed", severity=Severity.ERROR,
            message=f"{path.as_posix()} is a personal local file and must not be committed; "
                    f"remove it from version control and gitignore it.",
        )))
    return 0.0, diags


def _gitignore_line_covers(line: str, entry: str) -> bool:
    """True when a .gitignore line covers a local-file entry.

    Handles both a literal/substring match (the historical check) and
    gitignore-style glob patterns (e.g. ``.claude/*.local.*`` legitimately
    covers ``.claude/settings.local.json`` even though the two strings never
    appear as a substring of one another). Negated patterns (``!...``) are
    never treated as coverage.
    """
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("!"):
        return False
    if entry in line:
        return True
    pattern = line.lstrip("/")
    basename = entry.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(entry, pattern) or fnmatch.fnmatch(basename, pattern)


@rule(
    id="safety.local-files.gitignored", pillar=Pillar.SAFETY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/settings#settings-files",
    summary=".gitignore covers CLAUDE.local.md and .claude/settings.local.json.",
    platforms=_CLAUDE_ONLY,
    why="Without gitignore entries, personal Claude files are one `git add -A` away from being committed.",
    fix="Add CLAUDE.local.md and .claude/settings.local.json entries to .gitignore.",
    effort="mechanical",
)
def check_local_files_gitignored(index: ArtifactIndex):
    has_claude_artifact = (
        index.claude_md is not None
        or index.claude_settings is not None
        or bool(index.claude_rules)
        or any(a.rel_path.parts[0] == ".claude" for a in index.agents)
    )
    if not has_claude_artifact:
        return None  # N/A: repository has no Claude artifacts to protect
    lines = index.facts.gitignore_lines if index.facts is not None else ()
    missing = [
        entry for entry in config.LOCAL_FILE_GITIGNORE_ENTRIES
        if not any(_gitignore_line_covers(line, entry) for line in lines)
    ]
    if not missing:
        return 1.0, []
    diags = [
        Diagnostic(
            rule_id="safety.local-files.gitignored", severity=Severity.WARNING,
            message=f".gitignore has no entry covering {entry}; personal Claude files "
                    f"can be committed by accident.",
        )
        for entry in missing
    ]
    return 0.0, diags


def _walk_bypass(node: Any, path: str, hits: list[tuple[str, str]]) -> None:
    """Collect (json_path, reason) for every permission-bypass signal, in
    sorted-key order so diagnostics are deterministic."""
    if isinstance(node, dict):
        for key in sorted(node, key=str):
            value = node[key]
            child = f"{path}.{key}" if path else str(key)
            if key == _BYPASS_KEY and value:
                hits.append((child, f"'{_BYPASS_KEY}' is enabled"))
            _walk_bypass(value, child, hits)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_bypass(item, f"{path}[{i}]", hits)
    elif node == _BYPASS_VALUE:
        hits.append((path, f"value is '{_BYPASS_VALUE}'"))


@rule(
    id="safety.permissions.no-bypass", pillar=Pillar.SAFETY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
    source=RuleSource.ADVISORY,  # allowlisted: objective config value
    doc_url="https://code.claude.com/docs/en/settings#permission-settings",
    summary="Committed .claude/settings.json does not bypass the permission system.",
    platforms=_CLAUDE_ONLY,
    why="A committed bypassPermissions default disables the permission system for every contributor's agent runs.",
    fix="Remove bypassPermissions / dangerouslySkipPermissions from committed settings and grant narrow allow rules instead.",
    effort="mechanical",
)
def check_permissions_no_bypass(index: ArtifactIndex):
    settings = index.claude_settings
    if settings is None or settings.json_data is None:
        return None  # N/A: no parseable committed settings
    hits: list[tuple[str, str]] = []
    _walk_bypass(settings.json_data, "", hits)
    if not hits:
        return 1.0, []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for json_path, reason in hits:
        diags.append((settings.rel_path, Diagnostic(
            rule_id="safety.permissions.no-bypass", severity=Severity.ERROR,
            message=f"Committed settings bypass the permission system at "
                    f"'{json_path or '<root>'}': {reason}.",
        )))
    return 0.0, diags


@rule(
    id="safety.settings.valid", pillar=Pillar.SAFETY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC,
    doc_url="https://code.claude.com/docs/en/settings",
    summary=".claude/settings.json parses as JSON and uses only known top-level keys.",
    platforms=_CLAUDE_ONLY,
    why="A malformed settings file or unknown keys are silently ignored, so the configuration does not do what its authors think.",
    fix="Fix the JSON syntax and remove or correct unknown top-level keys in .claude/settings.json.",
    effort="mechanical",
)
def check_settings_valid(index: ArtifactIndex):
    settings = index.claude_settings
    if settings is None:
        return None  # N/A: no committed settings file
    if settings.parse_error is not None:
        return 0.0, [(settings.rel_path, Diagnostic(
            rule_id="safety.settings.valid", severity=Severity.ERROR,
            message=f".claude/settings.json is not valid JSON: {settings.parse_error}",
        ))]
    if not isinstance(settings.json_data, dict):
        return 0.0, [(settings.rel_path, Diagnostic(
            rule_id="safety.settings.valid", severity=Severity.ERROR,
            message=".claude/settings.json must contain a top-level JSON object.",
        ))]
    unknown = sorted(
        str(k) for k in settings.json_data
        if str(k) not in config.KNOWN_CLAUDE_SETTINGS_KEYS
    )
    if not unknown:
        return 1.0, []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for key in unknown:
        # ERROR, not WARNING: this rule's meta severity is ERROR, and a rule
        # that fails with only sub-ERROR diagnostics would trip the grade cap
        # and --fail-on error while rendering zero error findings to fix.
        diags.append((settings.rel_path, Diagnostic(
            rule_id="safety.settings.valid", severity=Severity.ERROR,
            message=f"Unknown top-level settings key '{key}' — Claude Code ignores it silently.",
        )))
    return 0.0, diags


@rule(
    id="safety.settings.no-secrets", pillar=Pillar.SAFETY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
    source=RuleSource.ADVISORY,  # allowlisted: shape-validated credential match
    doc_url="https://code.claude.com/docs/en/settings#environment-variables",
    summary="The settings `env` block contains no credential-shaped literals.",
    platforms=_CLAUDE_ONLY,
    why="Secrets committed in the settings env block are credentials leaked to everyone with repository access.",
    fix="Replace secret literals in the env block with a secret manager reference or move them to untracked local settings.",
    effort="mechanical",
)
def check_settings_no_secrets(index: ArtifactIndex):
    settings = index.claude_settings
    if settings is None or not isinstance(settings.json_data, dict):
        return None
    env = settings.json_data.get("env")
    if not isinstance(env, dict):
        return None  # N/A: no env block to scan
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for key in sorted(env, key=str):
        value = env[key]
        if not isinstance(value, str):
            continue
        if any(p.search(value) for p in _SECRET_RES):
            diags.append((settings.rel_path, Diagnostic(
                rule_id="safety.settings.no-secrets", severity=Severity.ERROR,
                message=f"env value for '{key}' matches a credential shape; "
                        f"never commit secrets in .claude/settings.json.",
            )))
    if diags:
        return 0.0, diags
    return 1.0, []


@rule(
    id="safety.injection.surface", pillar=Pillar.SAFETY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://cwe.mitre.org/data/definitions/829.html",
    summary="AI instruction files do not pipe remote scripts straight into a shell.",
    why="Instructions telling an agent to pipe a remote script into a shell are an unauditable remote-code-execution surface.",
    fix="Replace curl|sh / wget|sh / iwr|iex commands with pinned, reviewable install steps.",
    effort="authoring",
)
def check_injection_surface(index: ArtifactIndex):
    # index.skills is derived from the SKILL artifacts, so iterating the
    # markdown artifacts (a.doc is not None) covers skills exactly once.
    docs = [a for a in index.artifacts if a.doc is not None]
    if not docs:
        return None  # N/A: no markdown instruction surface to scan
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for artifact in sorted(docs, key=lambda a: a.rel_path.as_posix()):
        body = artifact.doc.body
        for label, pattern in _INJECTION_RES:
            if pattern.search(body):
                diags.append((artifact.rel_path, Diagnostic(
                    rule_id="safety.injection.surface", severity=Severity.WARNING,
                    message=f"{artifact.rel_path.as_posix()} instructs piping a remote "
                            f"script into a shell ({label}); this is an unauditable "
                            f"code-execution surface.",
                )))
    if diags:
        return 0.0, diags
    return 1.0, []
