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
