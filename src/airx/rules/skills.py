"""Skill-file (SKILL.md) validation rules.

Vendored and adapted from AgentEval (github.com/YoavLax/AgentEval,
`src/agenteval/rules/{frontmatter,description,disclosure,sizing,references,compat}.py`,
MIT licensed), per plan.md open question 2 (resolved: vendor rather than
depend on the `agenteval` package — see `airx/config.py` for the rationale).

Every rule function returns `(satisfaction, diagnostics)` or `None`:
  * `None` means the rule does not apply to this file (e.g. there is no
    `description` field to grade because it's already missing — that is
    reported by a separate required-field rule instead of being
    double-counted here).
  * binary rules return `(1.0, [])` on pass or `(0.0, [Diagnostic(...)])` on
    fail.
  * `check_description_quality` is graded: it returns a continuous
    `score / 100.0` in [0, 1].
  * `check_compat_claude_only` / `check_compat_unverified` are purely
    informational (per plan.md pillar 4): they always return `1.0` and only
    attach INFO diagnostics for visibility, since using a Claude-only field is
    not itself a mistake.
"""
from __future__ import annotations

import re
from pathlib import Path

from airx import config
from airx.model import Applicability, Diagnostic, ParsedDocument, Pillar, RuleSource, Severity
from airx.rules.registry import RuleScope, rule
from airx.tokenizer import estimate_tokens

# --- shared patterns (vendored from agenteval/rules/frontmatter.py & description.py) ---

_XML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")
_NAME_VALID_CHARS_RE = re.compile(r"^[a-z0-9-]+$")
_YAML_ANCHOR_RE = re.compile(r"&([A-Za-z_][A-Za-z0-9_-]*)")
_YAML_ALIAS_RE = re.compile(r"\*([A-Za-z_][A-Za-z0-9_-]*)")

_FIRST_PERSON_RE = re.compile(
    r"(?:(?:^|(?<=\.\s))I\b)"
    r"|\bI(?:can|will|am|do|have|would|should|need|shall|won't|didn't|don't)\b"
    r"|\bMy\b",
    re.MULTILINE,
)
_SECOND_PERSON_RE = re.compile(r"\b[Yy]ou(?:can|will|should|must|need|are|have|do|get|use)\b")

_ACTION_VERBS = frozenset({
    "generates", "analyzes", "validates", "deploys", "processes", "creates", "builds",
    "converts", "extracts", "formats", "monitors", "scans", "parses", "transforms",
    "compiles", "tests", "checks", "lints", "runs", "executes", "fetches", "sends",
    "uploads", "downloads", "configures", "sets", "updates", "installs", "removes",
    "detects", "identifies", "classifies", "scores", "ranks", "summarizes", "translates",
    "encrypts", "decrypts", "automates", "scaffolds", "provisions", "migrates", "syncs",
    "generate", "analyze", "validate", "deploy", "process", "create", "build", "convert",
    "extract", "format", "monitor", "scan", "parse", "transform", "compile", "test",
    "check", "lint", "run", "execute", "fetch", "send", "upload", "download", "configure",
    "set", "update", "install", "remove", "detect", "identify", "classify", "score",
    "rank", "summarize", "translate", "encrypt", "decrypt", "automate", "scaffold",
    "provision", "migrate", "sync",
})

_TRIGGER_PATTERNS = [
    re.compile(r"\buse\s+(?:this\s+)?(?:skill\s+)?when\b", re.IGNORECASE),
    re.compile(r"\bactivate\s+(?:this\s+)?(?:skill\s+)?(?:for|when)\b", re.IGNORECASE),
    re.compile(r"\brun\s+(?:this\s+)?(?:skill\s+)?when\b", re.IGNORECASE),
    re.compile(r"\binvoke\s+(?:this\s+)?(?:skill\s+)?when\b", re.IGNORECASE),
    re.compile(r"\bwhenever\s+(?:the\s+)?user\s+(?:mentions?|asks?|requests?|needs?|wants?)\b", re.IGNORECASE),
    re.compile(r"\bmake\s+sure\s+to\s+use\s+this\s+skill\b", re.IGNORECASE),
    re.compile(r"\btrigger(?:s|ed)?\s+(?:when|for|by)\b", re.IGNORECASE),
]

_VAGUE_WORDS = frozenset({
    "tool", "helper", "utility", "stuff", "things", "various", "general", "generic",
    "simple", "basic", "easy", "nice", "good", "great", "awesome", "cool", "helpful",
    "useful", "important", "powerful", "flexible", "robust", "comprehensive",
    "efficient", "effective", "handles",
})

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "shall", "should", "may", "might",
    "must", "can", "could", "of", "in", "to", "for", "with", "on", "at", "from", "by",
    "about", "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "again", "further", "then", "once", "and", "but", "or", "nor",
    "not", "so", "yet", "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "only", "own", "same", "than", "too", "very", "just", "because", "if", "when",
    "where", "how", "all", "any", "this", "that", "these", "those", "it", "its",
})

_CODE_BLOCK_RE = re.compile(r"^(?:```|~~~)[^\n]*\n(.*?)^(?:```|~~~)\s*$", re.MULTILINE | re.DOTALL)
_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")
_BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/]{64,}={0,2}")
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?!https?://|mailto:)([^)\s#]+)(?:#[^)]*)?\)")
_DIRECTIVE_RE = re.compile(r"(?:source|file|include):\s*([^\s]+\.[a-zA-Z0-9]+)", re.IGNORECASE)


def _is_real_base64(text: str) -> bool:
    return any(c.isupper() for c in text) and any(c.islower() for c in text)


def _field_line(raw_text: str, field: str) -> int | None:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            break
        if line.lstrip().startswith(f"{field}:"):
            return i
    return None


# --- description quality scorer (vendored from agenteval/rules/description.py) ---

def _score_action_verbs(desc: str) -> tuple[int, str | None]:
    words = re.findall(r"[a-zA-Z]+", desc)
    if not words:
        return 0, "Description has no words."
    first_word = words[0].lower()
    has_leading_verb = first_word in _ACTION_VERBS
    verb_count = sum(1 for w in words if w.lower() in _ACTION_VERBS)
    if has_leading_verb and verb_count >= 2:
        return 25, None
    if has_leading_verb:
        return 20, None
    if verb_count >= 2:
        return 15, "Start the description with an action verb (e.g., 'Generates...', 'Validates...')."
    if verb_count == 1:
        return 10, "Start the description with an action verb (e.g., 'Generates...', 'Validates...')."
    return 0, "No action verbs found. Use verbs like 'Generates', 'Analyzes', 'Validates'."


def _score_trigger_phrases(desc: str) -> tuple[int, str | None]:
    matches = sum(1 for p in _TRIGGER_PATTERNS if p.search(desc))
    if matches >= 2:
        return 25, None
    if matches == 1:
        return 20, None
    weak_signals = [
        re.compile(r"\bfor\s+\w+ing\b", re.IGNORECASE),
        re.compile(r"\bto\s+\w+\b", re.IGNORECASE),
    ]
    weak = sum(1 for p in weak_signals if p.search(desc))
    if weak:
        return 10, "Add explicit trigger phrases like 'Use when...' or 'Activate for...'."
    return 0, "No trigger context found. Add phrases like 'Use this skill whenever the user mentions...'."


def _score_keyword_density(desc: str) -> tuple[int, str | None]:
    words = re.findall(r"[a-zA-Z]+", desc)
    if not words:
        return 0, "Description is empty."
    content_words = [w for w in words if w.lower() not in _STOP_WORDS]
    ratio = len(content_words) / len(words) if words else 0
    if ratio >= 0.6:
        return 25, None
    if ratio >= 0.45:
        return 20, None
    if ratio >= 0.3:
        return 15, "Replace filler words with domain-specific keywords."
    return 5, "Description is mostly filler. Use specific terms for the task domain."


def _score_specificity(desc: str) -> tuple[int, str | None]:
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", desc)]
    if not words:
        return 0, "Description is empty."
    vague_count = sum(1 for w in words if w in _VAGUE_WORDS)
    vague_ratio = vague_count / len(words) if words else 0
    if vague_ratio == 0:
        return 15, None
    if vague_ratio <= 0.1:
        return 10, None
    if vague_ratio <= 0.2:
        return 5, f"Reduce vague terms ({vague_count} found). Be specific about what the skill does."
    return 0, f"Too many vague words ({vague_count} found: 'tool', 'helper', etc.). Name the exact actions and domains."


def _score_length(desc: str) -> tuple[int, str | None]:
    length = len(desc.strip())
    if length < 20:
        return 0, f"Description is too short ({length} chars). Provide enough detail for agent routing."
    if length < 40:
        return 3, "Description is short. Add more context about when to use this skill."
    if length > 500:
        return 3, f"Description is long ({length} chars). Keep it concise; move details to the body."
    if length > 300:
        return 7, "Description is getting long. Consider trimming to the essentials."
    return 10, None


def score_description(desc: str) -> tuple[int, list[str]]:
    """Score a description string from 0-100 with improvement suggestions."""
    scorers = [_score_action_verbs, _score_trigger_phrases, _score_keyword_density, _score_specificity, _score_length]
    total = 0
    suggestions: list[str] = []
    for scorer in scorers:
        points, suggestion = scorer(desc)
        total += points
        if suggestion:
            suggestions.append(suggestion)
    return total, suggestions


def _extract_references(body: str) -> list[str]:
    refs: list[str] = []
    refs.extend(_MD_LINK_RE.findall(body))
    refs.extend(_DIRECTIVE_RE.findall(body))
    seen: set[str] = set()
    unique: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def _reference_depth(ref_path: str) -> int:
    parts = Path(ref_path).parts
    dir_parts = parts[:-1] if len(parts) > 1 else ()
    return len(dir_parts)


# =============================================================================
# name.*
# =============================================================================

@rule(
    id="skills.name.required", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` field is present in SKILL.md frontmatter.",
)
def check_name_required(doc: ParsedDocument):
    if doc.frontmatter.get("name") is None:
        return 0.0, [Diagnostic(rule_id="skills.name.required", severity=Severity.ERROR,
                                 message="Required field 'name' is missing from frontmatter.")]
    return 1.0, []


@rule(
    id="skills.name.type", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` is a YAML string, not a value silently coerced to boolean/number/null.",
)
def check_name_type(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if name is None or isinstance(name, str):
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.name.type", severity=Severity.ERROR,
        message=f"Field 'name' must be a string but YAML parsed it as {type(name).__name__} ({name!r}). "
                f"Quote the value: name: \"{name}\"",
        line=_field_line(doc.raw_text, "name"),
    )]


@rule(
    id="skills.name.max-length", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` is 64 characters or fewer.",
)
def check_name_max_length(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    if len(name) <= config.NAME_MAX_LENGTH:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.name.max-length", severity=Severity.ERROR,
                             message=f"Name exceeds {config.NAME_MAX_LENGTH} characters (got {len(name)}): '{name}'.")]


@rule(
    id="skills.name.charset", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` uses lowercase letters, numbers, and hyphens only.",
)
def check_name_charset(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    if _NAME_VALID_CHARS_RE.match(name):
        return 1.0, []
    invalid = sorted(set(c for c in name if not re.match(r"[a-z0-9-]", c)))
    return 0.0, [Diagnostic(
        rule_id="skills.name.charset", severity=Severity.ERROR,
        message=f"Name contains invalid characters {invalid}: '{name}'. Use lowercase letters, numbers, and hyphens only.",
    )]


@rule(
    id="skills.name.hyphens", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` has no leading/trailing hyphen and no consecutive hyphens.",
)
def check_name_hyphens(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    issues = []
    if name.startswith("-"):
        issues.append("starts with a hyphen")
    if name.endswith("-"):
        issues.append("ends with a hyphen")
    if "--" in name:
        issues.append("contains consecutive hyphens")
    if not issues:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.name.hyphens", severity=Severity.ERROR,
                             message=f"Name '{name}' {' and '.join(issues)}.",
                             line=_field_line(doc.raw_text, "name"))]


@rule(
    id="skills.name.reserved", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` does not contain the reserved words 'claude' or 'anthropic'.",
)
def check_name_reserved(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    for word in ("anthropic", "claude"):
        if word in name:
            return 0.0, [Diagnostic(rule_id="skills.name.reserved", severity=Severity.ERROR,
                                     message=f"Name contains reserved word '{word}': '{name}'.")]
    return 1.0, []


@rule(
    id="skills.name.dirname-match", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` matches the parent directory name. VS Code/Copilot silently drops mismatches.",
)
def check_name_dirname_match(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    parent = doc.path.parent.name
    if parent and parent != name:
        return 0.0, [Diagnostic(
            rule_id="skills.name.dirname-match", severity=Severity.ERROR,
            message=f"Name '{name}' does not match parent directory '{parent}'. "
                    f"VS Code/Copilot silently fails to load this skill.",
        )]
    return 1.0, []


# =============================================================================
# description.*
# =============================================================================

@rule(
    id="skills.description.required", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#description-field",
    summary="`description` field is present in SKILL.md frontmatter.",
)
def check_description_required(doc: ParsedDocument):
    if doc.frontmatter.get("description") is None:
        return 0.0, [Diagnostic(rule_id="skills.description.required", severity=Severity.ERROR,
                                 message="Required field 'description' is missing from frontmatter.")]
    return 1.0, []


@rule(
    id="skills.description.type", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#description-field",
    summary="`description` is a YAML string, not a value silently coerced by the parser.",
)
def check_description_type(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if desc is None or isinstance(desc, str):
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.description.type", severity=Severity.ERROR,
        message=f"Field 'description' must be a string but YAML parsed it as {type(desc).__name__} ({desc!r}).",
        line=_field_line(doc.raw_text, "description"),
    )]


@rule(
    id="skills.description.non-empty", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#description-field",
    summary="`description` is not blank or whitespace-only.",
)
def check_description_non_empty(doc: ParsedDocument):
    if "description" not in doc.frontmatter:
        return None
    desc = doc.frontmatter.get("description")
    if not desc or (isinstance(desc, str) and not desc.strip()):
        return 0.0, [Diagnostic(rule_id="skills.description.non-empty", severity=Severity.ERROR,
                                 message="Description is empty.", line=_field_line(doc.raw_text, "description"))]
    return 1.0, []


@rule(
    id="skills.description.max-length", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#description-field",
    summary="`description` is 1024 characters or fewer.",
)
def check_description_max_length(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str) or not desc:
        return None
    if len(desc) <= config.DESCRIPTION_MAX_LENGTH:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.description.max-length", severity=Severity.ERROR,
                             message=f"Description exceeds {config.DESCRIPTION_MAX_LENGTH} characters (got {len(desc)}).",
                             line=_field_line(doc.raw_text, "description"))]


@rule(
    id="skills.description.no-xml", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#description-field",
    summary="`description` contains no XML/HTML markup.",
)
def check_description_no_xml(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str) or not desc:
        return None
    tags = _XML_TAG_RE.findall(desc)
    if not tags:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.description.no-xml", severity=Severity.ERROR,
                             message=f"Description contains XML/HTML tags: {tags}.")]


@rule(
    id="skills.description.person-voice", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    summary="`description` is written in third person, not first/second person.",
)
def check_description_person_voice(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str) or not desc:
        return None
    m = _FIRST_PERSON_RE.search(desc)
    if m:
        return 0.0, [Diagnostic(rule_id="skills.description.person-voice", severity=Severity.ERROR,
                                 message=f"Description uses first-person voice ('{m.group().strip()}'). "
                                         f"Use third person, e.g. 'Generates...' or 'Validates...'.")]
    m = _SECOND_PERSON_RE.search(desc)
    if m:
        return 0.0, [Diagnostic(rule_id="skills.description.person-voice", severity=Severity.ERROR,
                                 message=f"Description uses second-person voice ('{m.group()}'). "
                                         f"Use third person, e.g. 'Generates...' or 'Validates...'.")]
    return 1.0, []


@rule(
    id="skills.description.quality", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=8, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    summary="Graded 0-100 score of description discoverability (action verbs, trigger phrases, "
            "keyword density, specificity, length).",
)
def check_description_quality(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return None
    score, suggestions = score_description(desc)
    suffix = " Suggestions: " + "; ".join(suggestions) if suggestions else ""
    return (
        score / 100.0,
        [Diagnostic(rule_id="skills.description.quality", severity=Severity.INFO,
                     message=f"Description quality score: {score}/100.{suffix}")],
    )


@rule(
    id="skills.description.min-score", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    summary=f"Description quality score meets the {config.MIN_DESCRIPTION_SCORE_DEFAULT}/100 floor.",
)
def check_description_min_score(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return None
    score, suggestions = score_description(desc)
    if score >= config.MIN_DESCRIPTION_SCORE_DEFAULT:
        return 1.0, []
    suffix = " " + "; ".join(suggestions) if suggestions else ""
    return 0.0, [Diagnostic(
        rule_id="skills.description.min-score", severity=Severity.WARNING,
        message=f"Description quality score {score}/100 is below the minimum threshold of "
                f"{config.MIN_DESCRIPTION_SCORE_DEFAULT}.{suffix}",
    )]


# =============================================================================
# frontmatter.*
# =============================================================================

@rule(
    id="skills.frontmatter.unknown-fields", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#frontmatter",
    summary="Frontmatter has no fields outside the known SKILL.md schema.",
)
def check_unknown_fields(doc: ParsedDocument):
    unknown = [f for f in doc.frontmatter if f not in config.KNOWN_FRONTMATTER_FIELDS]
    if not unknown:
        return 1.0, []
    diags = [Diagnostic(rule_id="skills.frontmatter.unknown-fields", severity=Severity.WARNING,
                         message=f"Unknown frontmatter field '{f}'.") for f in sorted(unknown)]
    return 0.0, diags


@rule(
    id="skills.frontmatter.yaml-anchors", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#frontmatter",
    summary="Frontmatter contains no YAML anchors/aliases, which silently copy values between fields.",
)
def check_yaml_anchors(doc: ParsedDocument):
    fm_raw = doc.frontmatter_raw
    if not fm_raw:
        return None
    anchors = _YAML_ANCHOR_RE.findall(fm_raw)
    aliases = _YAML_ALIAS_RE.findall(fm_raw)
    if not anchors and not aliases:
        return 1.0, []
    names = sorted(set(anchors + aliases))
    return 0.0, [Diagnostic(
        rule_id="skills.frontmatter.yaml-anchors", severity=Severity.WARNING,
        message=f"YAML anchors/aliases detected in frontmatter ({', '.join(names)}); "
                f"they silently copy values between fields and can bypass validation.",
    )]


# =============================================================================
# budget.* / sizing.* / bloat.* (progressive disclosure)
# =============================================================================

@rule(
    id="skills.budget.metadata", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#progressive-disclosure",
    summary="Frontmatter fits the ~100-token metadata budget.",
)
def check_budget_metadata(doc: ParsedDocument):
    if not doc.frontmatter_raw:
        return None
    tokens = estimate_tokens(doc.frontmatter_raw)
    if tokens <= config.METADATA_TOKEN_BUDGET:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.budget.metadata", severity=Severity.WARNING,
        message=f"Frontmatter uses ~{tokens} tokens, exceeding the ~{config.METADATA_TOKEN_BUDGET}-token metadata budget.",
    )]


@rule(
    id="skills.budget.body", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#progressive-disclosure",
    summary="Body fits the 5,000-token instruction budget.",
)
def check_budget_body(doc: ParsedDocument):
    if not doc.body.strip():
        return None
    tokens = estimate_tokens(doc.body)
    if tokens <= config.BODY_TOKEN_BUDGET:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.budget.body", severity=Severity.WARNING,
        message=f"Body uses ~{tokens} tokens, exceeding the {config.BODY_TOKEN_BUDGET}-token instruction budget. "
                f"Move large content blocks to referenced files.",
    )]


@rule(
    id="skills.sizing.lines", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#progressive-disclosure",
    summary="File is 500 lines or fewer.",
)
def check_sizing_lines(doc: ParsedDocument):
    n = doc.line_count
    if n <= config.MAX_BODY_LINES:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.sizing.lines", severity=Severity.WARNING,
                             message=f"File is {n} lines, exceeding the recommended {config.MAX_BODY_LINES}-line limit.")]


@rule(
    id="skills.sizing.tokens", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#progressive-disclosure",
    summary="File fits the 8,000-token overall budget.",
)
def check_sizing_tokens(doc: ParsedDocument):
    tokens = estimate_tokens(doc.raw_text)
    if tokens <= config.MAX_TOKENS:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.sizing.tokens", severity=Severity.WARNING,
                             message=f"File is ~{tokens} tokens, exceeding the {config.MAX_TOKENS}-token budget.")]


@rule(
    id="skills.bloat.code-blocks", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/best-practices",
    summary="No code block in the body exceeds 50 lines.",
)
def check_bloat_code_blocks(doc: ParsedDocument):
    if not doc.body:
        return 1.0, []
    diags = []
    for match in _CODE_BLOCK_RE.finditer(doc.body):
        line_count = len(match.group(1).splitlines())
        if line_count > config.BLOAT_CODE_BLOCK_LINES:
            diags.append(Diagnostic(
                rule_id="skills.bloat.code-blocks", severity=Severity.INFO,
                message=f"Code block with {line_count} lines found in body; blocks over "
                        f"{config.BLOAT_CODE_BLOCK_LINES} lines should move to a referenced file.",
            ))
    return (1.0, []) if not diags else (0.0, diags)


@rule(
    id="skills.bloat.tables", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/best-practices",
    summary="No table in the body exceeds 20 data rows.",
)
def check_bloat_tables(doc: ParsedDocument):
    if not doc.body:
        return 1.0, []
    rows = _TABLE_ROW_RE.findall(doc.body)
    data_rows = [r for r in rows if not _TABLE_SEPARATOR_RE.match(r)]
    if len(data_rows) <= config.BLOAT_TABLE_ROWS:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.bloat.tables", severity=Severity.INFO,
        message=f"Table with {len(data_rows)} data rows found in body; tables over "
                f"{config.BLOAT_TABLE_ROWS} rows should move to a referenced file.",
    )]


@rule(
    id="skills.bloat.base64", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/best-practices",
    summary="No base64-encoded blob is embedded in the body.",
)
def check_bloat_base64(doc: ParsedDocument):
    if not doc.body:
        return 1.0, []
    match = _BASE64_CANDIDATE_RE.search(doc.body)
    if match and _is_real_base64(match.group()):
        return 0.0, [Diagnostic(rule_id="skills.bloat.base64", severity=Severity.INFO,
                                 message="Base64-encoded content found in body; move binary data to a referenced file.")]
    return 1.0, []


# =============================================================================
# references.*
# =============================================================================

@rule(
    id="skills.references.resolve", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#file-references",
    summary="Relative file references in the body exist on disk and stay within the skill directory (CWE-59).",
)
def check_references_resolve(doc: ParsedDocument):
    refs = _extract_references(doc.body)
    if not refs:
        return None
    skill_dir = doc.path.parent.resolve()
    diags: list[Diagnostic] = []
    for ref in refs:
        target = (skill_dir / ref).resolve()
        if not target.is_relative_to(skill_dir):
            diags.append(Diagnostic(rule_id="skills.references.resolve", severity=Severity.ERROR,
                                     message=f"Reference '{ref}' resolves outside the skill directory ({target})."))
            continue
        if not target.exists():
            diags.append(Diagnostic(rule_id="skills.references.resolve", severity=Severity.ERROR,
                                     message=f"Referenced file does not exist: '{ref}'."))
    return (1.0, []) if not diags else (0.0, diags)


@rule(
    id="skills.references.depth", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#file-references",
    summary="File references stay one directory level deep from SKILL.md.",
)
def check_references_depth(doc: ParsedDocument):
    refs = _extract_references(doc.body)
    if not refs:
        return None
    diags = []
    for ref in refs:
        if ref.startswith(".."):
            diags.append(Diagnostic(rule_id="skills.references.depth", severity=Severity.WARNING,
                                     message=f"Reference '{ref}' traverses above the skill directory."))
        elif _reference_depth(ref) > 1:
            diags.append(Diagnostic(rule_id="skills.references.depth", severity=Severity.WARNING,
                                     message=f"Reference '{ref}' is more than one level deep from SKILL.md."))
    return (1.0, []) if not diags else (0.0, diags)


# =============================================================================
# compat.* (informational only — never reduces the score)
# =============================================================================

@rule(
    id="skills.compat.claude-only", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=1, severity=Severity.INFO,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#frontmatter",
    summary="Informational: flags frontmatter fields that only work in Claude Code.",
)
def check_compat_claude_only(doc: ParsedDocument):
    found = sorted(f for f in doc.frontmatter if f in config.CLAUDE_ONLY_FIELDS)
    diags = [Diagnostic(rule_id="skills.compat.claude-only", severity=Severity.INFO,
                         message=f"Field '{f}' is Claude Code-specific; ignored by VS Code/Copilot.")
             for f in found]
    return 1.0, diags


@rule(
    id="skills.compat.unverified", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=1, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#frontmatter",
    summary="Informational: flags frontmatter fields with unverified behavior in Codex/Cursor.",
)
def check_compat_unverified(doc: ParsedDocument):
    diags = []
    for field in sorted(doc.frontmatter):
        compat = config.COMPAT_MATRIX.get(field)
        if not compat:
            continue
        unknown_agents = sorted(a for a, status in compat.items() if status == "unknown")
        if unknown_agents:
            diags.append(Diagnostic(rule_id="skills.compat.unverified", severity=Severity.INFO,
                                     message=f"Behavior of field '{field}' in {', '.join(unknown_agents)} is unverified."))
    return 1.0, diags


# =============================================================================
# repo-scope: presence and parseability
# =============================================================================

@rule(
    id="skills.present", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=8, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/",
    summary="At least one SKILL.md exists in the repository.",
)
def check_skills_present(index):
    if index.skills:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.present", severity=Severity.WARNING,
        message="No SKILL.md files found. Agent Skills let both Copilot and Claude Code load "
                "domain-specific procedures on demand.",
    )]


@rule(
    id="skills.parses", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification",
    summary="Every discovered SKILL.md is valid UTF-8 with well-formed YAML frontmatter.",
)
def check_skills_parse(index):
    total = len(index.skills) + len(index.skill_parse_errors)
    if total == 0:
        return None
    diags = [
        Diagnostic(rule_id="skills.parses", severity=Severity.ERROR, message=f"Failed to parse {path}: {err}")
        for path, err in index.skill_parse_errors
    ]
    return (len(index.skills) / total), diags
