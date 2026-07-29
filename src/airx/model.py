"""Core data types shared across the AI Readiness Analyzer pipeline.

All types here are immutable (frozen dataclasses / enums) so that the scoring
pipeline stays a pure function of its inputs, per the determinism contract in
plan.md section 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RuleSource(str, Enum):
    """Whether a rule is derived from a published spec, or is an advisory
    best-practice heuristic."""

    SPEC = "spec"
    ADVISORY = "advisory"


class Platform(str, Enum):
    COPILOT = "copilot"
    CLAUDE = "claude"
    NEUTRAL = "neutral"


class Pillar(str, Enum):
    FOUNDATION = "foundation"
    SKILLS = "skills"
    # The remaining pillars from plan.md are declared here so reports can show
    # honest pillar coverage, but have no registered rules yet in this build
    # (see plan.md Roadmap milestones 2-4).
    QUALITY = "quality"
    SCOPING = "scoping"
    AGENTS = "agents"
    VERIFICATION = "verification"
    TOOLING = "tooling"
    SAFETY = "safety"


class Applicability(str, Enum):
    """Whether a rule counts toward a pillar's presence ratio or its quality
    ratio (see plan.md section 6.2)."""

    PRESENCE = "presence"
    QUALITY = "quality"


@dataclass(frozen=True)
class Diagnostic:
    """A single concrete violation (or informational note) surfaced by a rule."""

    rule_id: str
    severity: Severity
    message: str
    line: int | None = None
    context: str | None = None


class ParseError(Exception):
    """Raised when a file cannot be decoded as UTF-8 or has malformed YAML frontmatter."""


@dataclass(frozen=True)
class ParsedDocument:
    """A Markdown file split into optional YAML frontmatter and a body.

    Used for both SKILL.md files and plain entry points (copilot-instructions.md,
    CLAUDE.md, AGENTS.md) — an entry point simply has empty frontmatter.
    """

    path: Path
    frontmatter: Mapping[str, Any]
    frontmatter_raw: str
    body: str
    raw_text: str

    @property
    def line_count(self) -> int:
        return len(self.raw_text.splitlines())
