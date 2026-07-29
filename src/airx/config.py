"""Vendored thresholds from AgentEval (github.com/YoavLax/AgentEval), plus this
project's own scoring configuration.

The AgentEval-derived constants below are ported from `src/agenteval/config.py`
(MIT licensed), together with the description-quality scorer in
`airx.rules.skills` (ported from `agenteval/rules/description.py`) and the
frontmatter/sizing/disclosure/references/compat rule logic (ported from
`agenteval/rules/*.py`). They are vendored — copied into this repository and
versioned with it — rather than imported as a dependency on the `agenteval`
package.

Rationale (plan.md section 14, open question 2 — resolved):
  * this project's ruleset must be versioned together with its report schema
    (determinism guarantee D7: adding/reweighting a rule is a deliberate,
    reviewed change to *this* repository, not an incidental side effect of
    `pip install --upgrade agenteval`);
  * historical scores must stay reproducible even if AgentEval's own
    thresholds change upstream;
  * the two projects target different outputs (AgentEval: a file-level lint
    tool; this project: a whole-repository score), so vendoring avoids
    coupling release cadences while still crediting and reusing proven,
    battle-tested rule logic instead of reinventing it.
"""
from __future__ import annotations

# --- Vendored from agenteval/config.py --------------------------------------

NAME_MAX_LENGTH: int = 64
DESCRIPTION_MAX_LENGTH: int = 1024

MAX_BODY_LINES: int = 500
MAX_TOKENS: int = 8000

METADATA_TOKEN_BUDGET: int = 100
BODY_TOKEN_BUDGET: int = 5000

BLOAT_CODE_BLOCK_LINES: int = 50
BLOAT_TABLE_ROWS: int = 20

KNOWN_FRONTMATTER_FIELDS: frozenset[str] = frozenset({
    "name", "description", "version", "author", "tags", "allowed-tools",
    "model", "context", "agent", "hooks", "user-invocable",
    "disable-model-invocation", "skills", "mode", "license", "compatibility",
    "metadata", "argument-hint",
})

COMPAT_MATRIX: dict[str, dict[str, str]] = {
    "name":                     {"claude": "supported", "vscode": "supported", "codex": "supported", "cursor": "supported"},
    "description":              {"claude": "supported", "vscode": "supported", "codex": "supported", "cursor": "supported"},
    "version":                  {"claude": "supported", "vscode": "supported", "codex": "unknown", "cursor": "unknown"},
    "author":                   {"claude": "supported", "vscode": "supported", "codex": "unknown", "cursor": "unknown"},
    "tags":                     {"claude": "supported", "vscode": "supported", "codex": "unknown", "cursor": "unknown"},
    "allowed-tools":            {"claude": "supported", "vscode": "supported", "codex": "unknown", "cursor": "unknown"},
    "user-invocable":           {"claude": "supported", "vscode": "supported", "codex": "unknown", "cursor": "unknown"},
    "context":                  {"claude": "supported", "vscode": "supported", "codex": "unknown", "cursor": "unknown"},
    "model":                    {"claude": "supported", "vscode": "ignored", "codex": "unknown", "cursor": "unknown"},
    "disable-model-invocation": {"claude": "supported", "vscode": "ignored", "codex": "unknown", "cursor": "unknown"},
    "mode":                     {"claude": "supported", "vscode": "ignored", "codex": "unknown", "cursor": "unknown"},
    "hooks":                    {"claude": "supported", "vscode": "ignored", "codex": "unknown", "cursor": "unknown"},
    "agent":                    {"claude": "supported", "vscode": "ignored", "codex": "unknown", "cursor": "unknown"},
    "skills":                   {"claude": "supported", "vscode": "ignored", "codex": "unknown", "cursor": "unknown"},
}

CLAUDE_ONLY_FIELDS: frozenset[str] = frozenset({
    "model", "disable-model-invocation", "mode", "hooks", "agent", "skills",
})

# --- This project's own configuration ---------------------------------------

MIN_DESCRIPTION_SCORE_DEFAULT: int = 50
"""Floor used by the advisory `skills.description.min-score` rule."""

PILLAR_WEIGHTS: dict[str, int] = {
    "foundation": 20,
    "quality": 15,
    "scoping": 12,
    "skills": 15,
    "agents": 10,
    "verification": 12,
    "tooling": 8,
    "safety": 8,
}
# Sums to 100 (plan.md section 6.1). Pillars with zero registered rules in
# this build are excluded from the score and reported as `not scored`.

PRESENCE_WEIGHT: float = 0.40
QUALITY_WEIGHT: float = 0.60
# plan.md section 6.2

GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "A"),
    (80.0, "B"),
    (70.0, "C"),
    (55.0, "D"),
    (35.0, "E"),
    (0.0, "F"),
)
# plan.md section 6.6. Must stay sorted descending by threshold.

ERROR_CAPS_GRADE_AT: str = "C"
"""plan.md section 14, open question 4 — resolved: ANY unwaived error-severity
finding caps the overall grade at C, regardless of the arithmetic score. A
repository with a silently-broken skill or a malformed config file is not
"agent-ready" no matter how good the rest of its setup looks."""

ENTRYPOINT_MAX_LINES_HARD: int = 400
ENTRYPOINT_IDEAL_LINES: tuple[int, int] = (30, 150)

# --- v0.2.0: weight profiles (plan.md §6.1) ----------------------------------

PROFILES: dict[str, dict[str, int]] = {
    "standard": dict(PILLAR_WEIGHTS),
    "minimal": {
        "foundation": 35, "quality": 25, "scoping": 10, "skills": 0,
        "agents": 0, "verification": 15, "tooling": 5, "safety": 10,
    },
    "enterprise": {
        "foundation": 18, "quality": 12, "scoping": 10, "skills": 15,
        "agents": 7, "verification": 18, "tooling": 5, "safety": 15,
    },
}
# Each profile sums to 100. Weight 0 => pillar reported but not scored.

# --- v0.2.0: quality-pillar thresholds (plan-v2-fable.md §4.3) ---------------

MIN_DIRECTIVES_FOR_QUALITY: int = 3
MIN_DIRECTIVES_FOR_EMPHASIS: int = 5
SPECIFICITY_TARGET: float = 0.5
RATIONALE_TARGET: float = 0.25
EMPHASIS_MAX_RATIO: float = 0.30
DIRECTIVE_MAX_CHARS: int = 200

OBVIOUS_RULES: tuple[str, ...] = (
    "write clean code", "use meaningful names", "add comments",
    "follow best practices", "handle errors appropriately", "keep it dry",
    "use consistent indentation", "write good code",
)

STALE_MARKERS: tuple[str, ...] = ("TODO", "FIXME", "TBD", "XXX", "<placeholder>", "lorem ipsum")

# High-precision credential shapes (plan.md §13: tiny surface, shape-validated).
SECRET_SHAPE_PATTERNS: tuple[str, ...] = (
    r"ghp_[A-Za-z0-9]{36}",
    r"github_pat_[A-Za-z0-9_]{22,}",
    r"sk-ant-[A-Za-z0-9-]{20,}",
    r"sk-[A-Za-z0-9]{40,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[bpoas]-[A-Za-z0-9-]{10,}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)

# --- v0.2.0: scoping thresholds ----------------------------------------------

MONOLITH_LINES: int = 250

# --- v0.2.0: agents & prompts (plan-v2-fable.md §4.5) ------------------------

KNOWN_AGENT_FIELDS: frozenset[str] = frozenset({
    "name", "description", "tools", "model", "target", "argument-hint",
    "color", "temperature", "mode", "handoffs", "mcp-servers",
})
KNOWN_PROMPT_FIELDS: frozenset[str] = frozenset({
    "name", "description", "mode", "model", "tools", "agent", "argument-hint",
})
AGENT_MAX_LINES: int = 500
AGENT_MAX_TOKENS: int = 8000

# --- v0.2.0: safety (plan-v2-fable.md §4.8) ----------------------------------

KNOWN_CLAUDE_SETTINGS_KEYS: frozenset[str] = frozenset({
    "permissions", "env", "hooks", "model", "statusLine", "includeCoAuthoredBy",
    "cleanupPeriodDays", "apiKeyHelper", "defaultMode", "forceLoginMethod",
    "enableAllProjectMcpServers", "enabledMcpjsonServers", "disabledMcpjsonServers",
    "awsAuthRefresh", "awsCredentialExport", "outputStyle", "sandbox",
    "alwaysThinkingEnabled", "companyAnnouncements", "spinnerTipsEnabled",
    "$schema", "extraKnownMarketplaces", "plugins",
})

LOCAL_FILE_GITIGNORE_ENTRIES: tuple[str, ...] = (
    "CLAUDE.local.md",
    ".claude/settings.local.json",
)

# --- v0.2.0: skills disclosure thresholds ------------------------------------

DISCLOSURE_BODY_LINES: int = 300
MIN_DESCRIPTION_CONTENT_WORDS: int = 15
