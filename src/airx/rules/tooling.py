"""Tooling pillar: MCP server configuration and environment reproducibility
(plan-v2-fable.md §4.7).

Covers MCP config presence/validity/secret hygiene plus deterministic repo
facts from `airx.probe` (setup script, devcontainer, `.env` template,
toolchain version pins, documented package scripts). All eight rules are
repo-scoped; the MCP rules emit per-file `(rel_path, Diagnostic)` findings.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

from airx import config
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, Pillar, Platform, RuleSource, Severity
from airx.rules.registry import RuleScope, rule

#: Compiled high-precision credential shapes (config.SECRET_SHAPE_PATTERNS).
_SECRET_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in config.SECRET_SHAPE_PATTERNS
)

#: An `env` value at least this long that does not use `${...}` indirection is
#: treated as a committed literal credential (plan-v2-fable.md §4.7).
_ENV_LITERAL_MIN_LEN: int = 16
_ENV_INDIRECTION_MARKER: str = "${"

#: Container keys under which MCP server definitions live, in precedence order
#: (`mcpServers` in .mcp.json, `servers` in .vscode/mcp.json).
_MCP_SERVER_KEYS: tuple[str, ...] = ("mcpServers", "servers")

#: `tooling.scripts.documented` thresholds (plan-v2-fable.md §4.7).
_MIN_PACKAGE_SCRIPTS: int = 3
_MIN_SCRIPTS_DOCUMENTED: int = 2

#: Markdown inline-code span; single-backtick, single-line. Fence delimiters
#: (```) cannot match because the span content excludes backticks.
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _sorted_mcp(index: ArtifactIndex):
    return sorted(index.mcp, key=lambda a: a.rel_path.as_posix())


# --- MCP configuration -------------------------------------------------------

@rule(
    id="tooling.mcp.present", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=5, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://code.visualstudio.com/docs/copilot/chat/mcp-servers",
    summary="An MCP configuration exists (.mcp.json, .vscode/mcp.json, or mcp.json).",
    why="MCP servers give agents vetted, declared tool access instead of ad-hoc improvisation.",
    fix="Add an .mcp.json (or .vscode/mcp.json) declaring the MCP servers agents should use.",
    effort="additive",
)
def check_mcp_present(index: ArtifactIndex):
    if index.mcp:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.mcp.present", severity=Severity.INFO,
        message="No MCP configuration found (.mcp.json, .vscode/mcp.json, or mcp.json).",
    )]


@rule(
    id="tooling.mcp.valid", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC,
    doc_url="https://code.visualstudio.com/docs/copilot/chat/mcp-servers",
    summary="MCP configs are valid JSON and every server declares 'command' or 'url'.",
    why="A malformed MCP config silently disables every server it declares.",
    fix="Make each MCP file valid JSON whose server entries declare 'command' (stdio) or 'url' (remote).",
    effort="mechanical",
)
def check_mcp_valid(index: ArtifactIndex):
    if not index.mcp:
        return None  # N/A: no MCP files
    sats: list[float] = []
    diags: list[tuple[Any, Diagnostic]] = []
    for artifact in _sorted_mcp(index):
        file_diags: list[Diagnostic] = []
        data = artifact.json_data
        if artifact.parse_error is not None:
            file_diags.append(Diagnostic(
                rule_id="tooling.mcp.valid", severity=Severity.ERROR,
                message=f"{artifact.rel_path.name} is not valid JSON: {artifact.parse_error}",
            ))
        elif not isinstance(data, dict):
            file_diags.append(Diagnostic(
                rule_id="tooling.mcp.valid", severity=Severity.ERROR,
                message=f"{artifact.rel_path.name} must be a JSON object at the top level.",
            ))
        else:
            container: Any = None
            container_key: str | None = None
            for key in _MCP_SERVER_KEYS:
                if key in data:
                    container_key = key
                    container = data[key]
                    break
            if container_key is not None and not isinstance(container, dict):
                file_diags.append(Diagnostic(
                    rule_id="tooling.mcp.valid", severity=Severity.ERROR,
                    message=f"'{container_key}' must be an object mapping server names to definitions.",
                ))
            elif isinstance(container, dict):
                for server_name in sorted(container, key=str):
                    entry = container[server_name]
                    if not isinstance(entry, dict) or (
                        "command" not in entry and "url" not in entry
                    ):
                        file_diags.append(Diagnostic(
                            rule_id="tooling.mcp.valid", severity=Severity.ERROR,
                            message=f"MCP server '{server_name}' must declare 'command' (stdio) "
                                    f"or 'url' (remote).",
                        ))
        sats.append(0.0 if file_diags else 1.0)
        diags.extend((artifact.rel_path, d) for d in file_diags)
    return sum(sats) / len(sats), diags


def _iter_env_literal_keys(data: Any) -> Iterator[str]:
    """Yield keys of `env` dict values that are long literals without `${...}`
    indirection, walking the JSON structure in sorted-key order."""
    if isinstance(data, dict):
        for key in sorted(data, key=str):
            value = data[key]
            if key == "env" and isinstance(value, dict):
                for env_key in sorted(value, key=str):
                    env_val = value[env_key]
                    if (
                        isinstance(env_val, str)
                        and len(env_val) >= _ENV_LITERAL_MIN_LEN
                        and _ENV_INDIRECTION_MARKER not in env_val
                    ):
                        yield str(env_key)
            else:
                yield from _iter_env_literal_keys(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_env_literal_keys(item)


@rule(
    id="tooling.mcp.no-secrets", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
    source=RuleSource.ADVISORY,  # allowlisted: objective, shape-validated check
    doc_url="https://code.visualstudio.com/docs/copilot/chat/mcp-servers",
    summary="MCP configs contain no secret-shaped literals and no literal 'env' credentials.",
    why="Credentials committed in MCP configs leak to everyone who clones the repository.",
    fix="Replace literal secrets with ${env:VAR} indirection and rotate any exposed credential.",
    effort="mechanical",
)
def check_mcp_no_secrets(index: ArtifactIndex):
    if not index.mcp:
        return None  # N/A: no MCP files
    diags: list[tuple[Any, Diagnostic]] = []
    for artifact in _sorted_mcp(index):
        # Scan the raw JSON text so secrets are caught even in unparseable files.
        raw: str | None = None
        try:
            raw = (index.root / str(artifact.rel_path)).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            raw = None  # unreadable → skip the raw scan
        if raw is not None:
            for pattern in _SECRET_RES:
                for _ in pattern.finditer(raw):
                    diags.append((artifact.rel_path, Diagnostic(
                        rule_id="tooling.mcp.no-secrets", severity=Severity.ERROR,
                        message=f"{artifact.rel_path.name} contains a secret-shaped literal "
                                f"matching /{pattern.pattern}/; rotate it and use "
                                f"${{env:VAR}} indirection.",
                    )))
        if isinstance(artifact.json_data, (dict, list)):
            for env_key in _iter_env_literal_keys(artifact.json_data):
                diags.append((artifact.rel_path, Diagnostic(
                    rule_id="tooling.mcp.no-secrets", severity=Severity.ERROR,
                    message=f"MCP env value '{env_key}' is a literal of "
                            f"{_ENV_LITERAL_MIN_LEN}+ characters; use ${{env:VAR}} "
                            f"indirection instead of committing the value.",
                )))
    if diags:
        return 0.0, diags
    return 1.0, []


@rule(
    id="tooling.mcp.not-overloaded", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/mcp",
    summary=f"MCP configuration declares at most {config.MCP_SERVER_SOFT_CEILING} servers "
            f"across all files.",
    why="Real-world usage reports that declaring far more MCP servers than are actually used "
        "daily causes tool-selection confusion and eats context on every turn.",
    fix="Trim the MCP config to the servers actually used day to day; move the rest to a "
        "per-project or on-demand config instead of loading them in every session.",
    effort="mechanical",
)
def check_mcp_not_overloaded(index: ArtifactIndex):
    if not index.mcp:
        return None  # N/A: no MCP files
    names: set[str] = set()
    for artifact in _sorted_mcp(index):
        data = artifact.json_data
        if not isinstance(data, dict):
            continue
        for key in _MCP_SERVER_KEYS:
            container = data.get(key)
            if isinstance(container, dict):
                names.update(str(n) for n in container)
    count = len(names)
    if count <= config.MCP_SERVER_SOFT_CEILING:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.mcp.not-overloaded", severity=Severity.INFO,
        message=f"{count} MCP servers are declared, past the soft ceiling of "
                f"{config.MCP_SERVER_SOFT_CEILING}; trim to the ones actually used daily.",
    )]


# --- Repo-fact rules ---------------------------------------------------------

@rule(
    id="tooling.setup.script", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://docs.github.com/en/copilot/customizing-copilot/customizing-the-development-environment-for-copilot-coding-agent",
    summary="A setup script or devcontainer bootstraps the development environment.",
    why="Agents need a deterministic way to bootstrap the environment before they can run anything.",
    fix="Add a scripts/setup* or bootstrap* script, a 'setup' make target, or a devcontainer.",
    effort="additive",
)
def check_setup_script(index: ArtifactIndex):
    facts = index.facts
    if facts is None:
        return None
    if facts.has_setup_script:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.setup.script", severity=Severity.WARNING,
        message="No setup script found (scripts/setup*, bootstrap*, a 'setup' make target, "
                "or a devcontainer/Dockerfile).",
    )]


@rule(
    id="tooling.devcontainer", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://containers.dev/",
    summary="A container definition (.devcontainer/ or Dockerfile) exists.",
    why="A container definition gives agents a reproducible environment identical to CI.",
    fix="Add a .devcontainer/devcontainer.json or a Dockerfile describing the dev environment.",
    effort="additive",
)
def check_devcontainer(index: ArtifactIndex):
    facts = index.facts
    if facts is None:
        return None
    if facts.has_devcontainer:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.devcontainer", severity=Severity.INFO,
        message="No .devcontainer/ directory or Dockerfile found.",
    )]


@rule(
    id="tooling.copilot-setup-steps.present", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://docs.github.com/en/copilot/tutorials/cloud-agent/get-the-best-results"
            "#pre-installing-dependencies-in-github-copilots-environment",
    summary="A .github/workflows/copilot-setup-steps.yml pre-installs dependencies in "
            "Copilot cloud agent's ephemeral environment.",
    platforms=(Platform.COPILOT,),
    why="Without this workflow, Copilot cloud agent must discover and install dependencies "
        "itself by trial and error before it can build, test, or lint anything.",
    fix="Add .github/workflows/copilot-setup-steps.yml that installs the project's dependencies.",
    effort="additive",
)
def check_copilot_setup_steps_present(index: ArtifactIndex):
    if index.setup_steps is not None:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.copilot-setup-steps.present", severity=Severity.INFO,
        message="No .github/workflows/copilot-setup-steps.yml found; Copilot cloud agent must "
                "discover and install dependencies itself.",
    )]


@rule(
    id="tooling.env.example", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://12factor.net/config",
    summary="If .env is gitignored, a committed .env.example/.env.template documents the variables.",
    why="Without a committed template an agent cannot know which environment variables the project needs.",
    fix="Commit a .env.example listing the required variable names with placeholder values.",
    effort="mechanical",
)
def check_env_example(index: ArtifactIndex):
    facts = index.facts
    if facts is None:
        return None
    ignores_env = any(
        ".env" in line and ".env.example" not in line
        for line in facts.gitignore_lines
    )
    if not ignores_env:
        return None  # N/A: .env is not gitignored
    if facts.has_env_example:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.env.example", severity=Severity.WARNING,
        message=".gitignore excludes .env but no .env.example or .env.template "
                "documents the required variables.",
    )]


@rule(
    id="tooling.versions.pinned", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://github.com/nvm-sh/nvm#nvmrc",
    summary="Toolchain versions are pinned (.nvmrc, .tool-versions, .python-version, ...).",
    why="Unpinned toolchain versions make agent runs unreproducible across machines.",
    fix="Pin toolchain versions via .nvmrc, .tool-versions, .python-version, "
        "rust-toolchain.toml, or requires-python in pyproject.toml.",
    effort="mechanical",
)
def check_versions_pinned(index: ArtifactIndex):
    facts = index.facts
    if facts is None:
        return None
    if facts.version_pins:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="tooling.versions.pinned", severity=Severity.INFO,
        message="No toolchain version pin found (.nvmrc, .tool-versions, .python-version, "
                "rust-toolchain.toml, or requires-python in pyproject.toml).",
    )]


@rule(
    id="tooling.scripts.documented", pillar=Pillar.TOOLING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://code.claude.com/docs/en/memory#write-effective-instructions",
    summary="With 3+ package.json scripts, the entry point documents at least 2 as inline code.",
    why="Agents discover project workflows through the entry point, not by reading package.json.",
    fix="Mention the key package.json scripts as inline code (e.g. `npm run build`) in the entry point.",
    effort="authoring",
)
def check_scripts_documented(index: ArtifactIndex):
    facts = index.facts
    if facts is None:
        return None
    docs = index.entrypoint_docs()
    if len(facts.package_scripts) < _MIN_PACKAGE_SCRIPTS or not docs:
        return None  # N/A: too few scripts, or no entry point to document them in
    tokens: set[str] = set()
    for doc in docs:
        for span in _INLINE_CODE_RE.findall(doc.body):
            tokens.add(span.strip())
            tokens.update(span.split())
    mentioned = tuple(s for s in facts.package_scripts if s in tokens)
    if len(mentioned) >= _MIN_SCRIPTS_DOCUMENTED:
        return 1.0, []
    message = (
        f"Entry point documents {len(mentioned)} of {len(facts.package_scripts)} "
        f"package.json scripts as inline code; document at least "
        f"{_MIN_SCRIPTS_DOCUMENTED} (e.g. `npm run <script>`)."
    )
    return 0.0, [(path, Diagnostic(
        rule_id="tooling.scripts.documented", severity=Severity.WARNING, message=message,
    )) for path in index.entrypoint_paths()]
