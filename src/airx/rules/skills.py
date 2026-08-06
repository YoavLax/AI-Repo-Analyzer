"""Skill-file (SKILL.md) validation rules.

Vendored and adapted from AgentEval (github.com/YoavLax/AgentEval,
`src/agenteval/rules/{frontmatter,description,disclosure,sizing,references,compat}.py`,
MIT licensed), per plan.md open question 2 (resolved: vendor rather than
depend on the `agenteval` package — see `airx/config.py` for the rationale).
The v0.2.0 additions (plan-v2-fable.md §4.2) complete the AgentEval port:
namespace-free names, progressive-disclosure usage, load triggers, script
hygiene, and description coherence.

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

import posixpath
import re
from pathlib import Path, PurePosixPath

from airx import config, fs, markdown as md
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, ParsedDocument, Pillar, RuleSource, Severity
from airx.rules.registry import RuleScope, rule
from airx.tokenizer import estimate_tokens

# --- shared patterns (vendored from agenteval/rules/frontmatter.py & description.py) ---

_XML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")
_NAME_VALID_CHARS_RE = re.compile(r"^[a-z0-9-]+$")
_YAML_ANCHOR_RE = re.compile(r"&([A-Za-z_][A-Za-z0-9_-]*)")
_YAML_ALIAS_RE = re.compile(r"\*([A-Za-z_][A-Za-z0-9_-]*)")


def _is_placeholder_tag(tag: str, desc: str) -> bool:
    """True when `tag` (e.g. '<slug>', '<commit>', a C# generic '<T>') reads
    as a bare angle-bracket placeholder/non-markup token rather than real
    XML/HTML/JSX: no attributes, not self-closing, and no matching closing
    tag anywhere in the description. Real markup almost always carries an
    attribute (`<Link prefetch={true}>`) or a structural pairing
    (`<T>...</T>`); a lone bare token is overwhelmingly a documentation
    convention for 'insert the real value here', not markup that would leak
    into a consuming system as a literal tag."""
    inner = tag[1:-1]
    if "=" in inner or "/" in inner:
        return False
    name = inner.split()[0] if inner.split() else inner
    return f"</{name}>" not in desc

_FIRST_PERSON_RE = re.compile(
    r"(?:(?:^|(?<=\.\s))I\b)"
    r"|\bI\s+(?:can|will|am|do|have|would|should|need|shall|won't|didn't|don't)\b"
    r"|\bMy\b",
    re.MULTILINE,
)
_SECOND_PERSON_RE = re.compile(r"\b[Yy]ou\s+(?:can|will|should|must|need|are|have|do|get|use)\b")
# A "when you ..." clause (e.g. "Use when you need to fix a failing test") is
# a standard, encouraged trigger-condition construction (see
# _TRIGGER_PATTERNS below) describing when the *user* invokes the skill, not
# a second-person capability statement describing what the skill itself
# does \u2014 it must not be flagged as a style violation.
_TRIGGER_CLAUSE_YOU_RE = re.compile(r"\bwhen\s*$", re.IGNORECASE)

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

_CODE_BLOCK_RE = md.CODE_BLOCK_RE
_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")
_BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/]{64,}={0,2}")
# Excludes scheme-qualified URLs (already handled) and root-relative paths
# ("/docs/..."), which are the standard web convention for "relative to the
# site's domain root" (e.g. a docs page meant to resolve against
# https://example.com) rather than a reference to a file bundled with this
# skill \u2014 resolving them as filesystem paths produces findings about files
# nobody ever meant to ship.
_MD_LINK_RE = md.MD_LINK_RE
# Path-charset-only capture: excludes backticks, quotes, brackets, and angle
# brackets so "...input file: [`x.csv`](x.csv)" (an ordinary sentence ending
# in "file:", not a directive) and "source: <https://example.com/a.b>" can't
# smuggle markdown-link or autolink syntax into the captured "path".
_DIRECTIVE_RE = md.DIRECTIVE_RE

# --- v0.2.0 additions (plan-v2-fable.md §4.2) --------------------------------

_WORD_RE = re.compile(r"[a-zA-Z]+")

#: Characters that indicate a namespaced skill name; plugin loaders add
#: namespace prefixes automatically, so they must not appear in `name`.
_NAMESPACE_CHARS: tuple[str, ...] = ("/", ":")

#: A reference is considered conditionally loaded when the line mentioning it
#: (or a directly adjacent line) matches this pattern (plan-v2-fable.md §4.2).
_LOAD_TRIGGER_RE = md.LOAD_TRIGGER_RE

#: Literal substrings that mark a script as interactive (blocks agent sessions).
_INTERACTIVE_PATTERNS: tuple[str, ...] = ("input(", "read -p", "Read-Host", "prompt(")

#: Literal substrings that count as a help/usage surface in a script.
_HELP_PATTERNS: tuple[str, ...] = ("--help", "argparse", "click", "commander", "yargs")


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


#: Fenced code blocks commonly hold illustrative example syntax (a template for
#: a *generated* file, a sample CLI invocation) rather than live directives the
#: agent should load, so `airx.markdown.extract_references` strips them first.
#: Shared with `airx.rules.foundation` and, transitively, with `airx.ingest`,
#: which must fetch exactly the files these rules go on to read (D3).
_extract_references = md.extract_references


def _reference_depth(ref_path: str) -> int:
    parts = Path(ref_path).parts
    dir_parts = parts[:-1] if len(parts) > 1 else ()
    return len(dir_parts)


def _visible_files(root: Path) -> list[Path]:
    """Files under `root` that fs.scan would have recorded: no symlinks (files
    or ancestor dirs) and no excluded-dir components. Keeping rule input equal
    to the scanned tree preserves determinism guarantee D4/D9 — a repo whose
    scan is identical must score identically."""
    try:
        candidates = sorted(root.rglob("*"), key=lambda p: p.as_posix())
    except OSError:
        return []
    out: list[Path] = []
    for p in candidates:
        try:
            rel_parts = p.relative_to(root).parts
            if any(part in fs.DEFAULT_EXCLUDED_DIRS for part in rel_parts):
                continue
            if any((root.joinpath(*rel_parts[:i + 1])).is_symlink() for i in range(len(rel_parts))):
                continue
            if p.is_file():
                out.append(p)
        except OSError:
            continue
    return out


def _script_files(doc: ParsedDocument) -> list[Path] | None:
    """Scan-visible files under the `scripts/` directory next to SKILL.md,
    sorted for determinism; `None` when no such directory."""
    scripts_dir = doc.path.parent / "scripts"
    try:
        if scripts_dir.is_symlink() or not scripts_dir.is_dir():
            return None
    except OSError:
        return None
    return _visible_files(scripts_dir)


def _read_text_defensively(path: Path) -> str | None:
    """Read a file as UTF-8; unreadable or undecodable files are skipped."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# =============================================================================
# name.*
# =============================================================================

@rule(
    id="skills.name.required", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` field is present in SKILL.md frontmatter.",
    why="Without a name the skill cannot be indexed or invoked by agent platforms.",
    fix="Add a `name:` field to the SKILL.md frontmatter matching the directory name.",
    effort="additive",
    spec_quote="The required `name` field: Must be 1-64 characters",
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
    why="YAML silently coerces unquoted values, so the loaded name differs from what was written.",
    fix="Quote the name value so YAML parses it as a string.",
    effort="mechanical",
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
    why="Names over the 64-character spec limit may be rejected or truncated by loaders.",
    fix="Shorten the skill name to 64 characters or fewer.",
    effort="mechanical",
    spec_quote="The required `name` field: Must be 1-64 characters",
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
    why="Names outside lowercase letters, numbers, and hyphens are rejected by spec-conformant loaders.",
    fix="Rename the skill using lowercase letters, numbers, and hyphens only.",
    effort="mechanical",
    spec_quote="May only contain unicode lowercase alphanumeric characters (`a-z`, `0-9`) and hyphens (`-`)",
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
    why="Leading, trailing, or doubled hyphens violate the name grammar in the spec.",
    fix="Remove the leading, trailing, or consecutive hyphens from the name.",
    effort="mechanical",
    spec_quote="Must not start or end with a hyphen (`-`) ... Must not contain consecutive hyphens (`--`)",
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
    why="Names containing the reserved words 'claude' or 'anthropic' may be rejected by loaders.",
    fix="Rename the skill so it does not contain the reserved word.",
    effort="mechanical",
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
    summary="`name` matches the parent directory name, as the spec requires.",
    why="A mismatched name fails spec validation, so the skill cannot be packaged or "
        "uploaded through the Skills API even where an editor tolerates it.",
    fix="Rename the directory or the `name` field so the two match exactly.",
    effort="mechanical",
    spec_quote="Must match the parent directory name",
)
def check_name_dirname_match(doc: ParsedDocument):
    """Spec conformance, stated plainly.

    The consequence used to be given as "VS Code/Copilot silently fails to
    load this skill", which attributes to a name/directory mismatch what the
    VS Code page actually says about *invalid characters*: "Names with invalid
    characters cause the skill to silently fail to load." Claude Code is
    explicit that it does not behave that way at all — "In a personal or
    project skill, `name` sets only the display label shown in skill listings,
    and the command still comes from the directory or file name."

    What survives is the requirement itself, which is unambiguous, plus the
    place it genuinely bites: `skills-ref validate` and the packaging and
    upload paths that enforce the spec.
    """
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    parent = doc.path.parent.name
    if parent and parent != name:
        return 0.0, [Diagnostic(
            rule_id="skills.name.dirname-match", severity=Severity.ERROR,
            message=f"Name '{name}' does not match parent directory '{parent}'; the spec "
                    f"requires them to be identical.",
        )]
    return 1.0, []


@rule(
    id="skills.name.no-namespace", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#name-field",
    summary="`name` contains no namespace separator ('/' or ':'); plugins add prefixes automatically.",
    why="Plugin loaders add namespace prefixes automatically, so '/' or ':' in a name breaks resolution.",
    fix="Remove the namespace separator and use the bare skill name.",
    effort="mechanical",
    spec_quote="May only contain unicode lowercase alphanumeric characters (`a-z`, `0-9`) and hyphens (`-`)",
)
def check_name_no_namespace(doc: ParsedDocument):
    name = doc.frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return None
    found = [c for c in _NAMESPACE_CHARS if c in name]
    if not found:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.name.no-namespace", severity=Severity.ERROR,
        message=f"Name '{name}' contains namespace separator(s) {found}; plugins add namespace "
                f"prefixes automatically, so use the bare skill name.",
        line=_field_line(doc.raw_text, "name"),
    )]


# =============================================================================
# description.*
# =============================================================================

@rule(
    id="skills.description.required", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#description-field",
    summary="`description` field is present in SKILL.md frontmatter.",
    why="Agents route to skills solely via the description; without one the skill is never selected.",
    fix="Add a `description:` field explaining what the skill does and when to use it.",
    effort="additive",
    spec_quote="The required `description` field: Must be 1-1024 characters",
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
    why="YAML coercion turns an unquoted description into a non-string value the loader cannot use.",
    fix="Quote the description so YAML parses it as a string.",
    effort="mechanical",
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
    why="An empty description gives the routing model nothing to match against.",
    fix="Write a description covering what the skill does and when to use it.",
    effort="authoring",
    spec_quote="The required `description` field: Must be 1-1024 characters",
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
    why="Descriptions over the 1024-character spec limit blow the always-loaded metadata budget.",
    fix="Trim the description to the essentials and move detail into the body.",
    effort="authoring",
    spec_quote="The required `description` field: Must be 1-1024 characters",
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
    why="Markup in the description leaks into the agent's routing prompt as literal tags.",
    fix="Remove the XML/HTML tags from the description.",
    effort="mechanical",
)
def check_description_no_xml(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str) or not desc:
        return None
    tags = [tag for tag in _XML_TAG_RE.findall(desc) if not _is_placeholder_tag(tag, desc)]
    if not tags:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="skills.description.no-xml", severity=Severity.ERROR,
                             message=f"Description contains XML/HTML tags: {tags}.")]


@rule(
    id="skills.description.person-voice", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    summary="`description` is written in third person, not first/second person.",
    why="First/second-person voice confuses routing, which expects a third-person capability statement.",
    fix="Rewrite the description in third person, e.g. 'Generates...' or 'Validates...'.",
    effort="authoring",
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
    for m in _SECOND_PERSON_RE.finditer(desc):
        if _TRIGGER_CLAUSE_YOU_RE.search(desc[:m.start()]):
            continue
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
    why="Discoverable descriptions with action verbs and trigger phrases decide whether the skill is ever loaded.",
    fix="Add action verbs, explicit 'Use when...' triggers, and domain keywords to the description.",
    effort="authoring",
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
    why="A very weak description means the agent will rarely select this skill.",
    fix="Rewrite the description with action verbs, trigger phrases, and specific domain terms.",
    effort="authoring",
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


@rule(
    id="skills.coherence", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/optimizing-descriptions",
    summary=f"Description carries at least {config.MIN_DESCRIPTION_CONTENT_WORDS} content words "
            f"(non-stopword), enough signal to route on.",
    why="A description with almost no content words gives the routing model too little signal to match on.",
    fix="Expand the description with the specific tasks, inputs, and trigger phrases the skill covers.",
    effort="authoring",
)
def check_coherence(doc: ParsedDocument):
    desc = doc.frontmatter.get("description")
    if not isinstance(desc, str):
        return None
    words = _WORD_RE.findall(desc)
    content_words = [w for w in words if w.lower() not in _STOP_WORDS]
    if len(content_words) >= config.MIN_DESCRIPTION_CONTENT_WORDS:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.coherence", severity=Severity.INFO,
        message=f"Description is too narrow: {len(content_words)} content word(s), below the "
                f"{config.MIN_DESCRIPTION_CONTENT_WORDS}-word minimum for reliable routing.",
        line=_field_line(doc.raw_text, "description"),
    )]


# =============================================================================
# frontmatter.*
# =============================================================================

@rule(
    id="skills.frontmatter.unknown-fields", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#frontmatter",
    summary="Frontmatter has no fields outside the known SKILL.md schema.",
    why="Unknown fields are silently ignored by loaders, hiding typos of meaningful fields.",
    fix="Remove or rename the fields to match the documented SKILL.md schema.",
    effort="mechanical",
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
    why="Anchors and aliases silently copy values between fields and can bypass validation.",
    fix="Replace the YAML anchors and aliases with literal values.",
    effort="mechanical",
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
    why="Every skill's frontmatter is always loaded, so oversized metadata taxes each session.",
    fix="Trim the frontmatter to a name plus a concise description.",
    effort="authoring",
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
    why="Bodies past the instruction budget dilute adherence once the skill loads.",
    fix="Move large content blocks into referenced files loaded on demand.",
    effort="authoring",
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
    why="Files past 500 lines flood the context window and dilute instruction adherence.",
    fix="Split the content into referenced files under the skill directory.",
    effort="authoring",
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
    why="Files past the 8,000-token budget crowd out task context when loaded.",
    fix="Move reference material into separate files loaded on demand.",
    effort="authoring",
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
    why="Long inline code blocks consume the loaded-context budget without being progressively disclosed.",
    fix="Move code blocks over 50 lines into referenced script files.",
    effort="authoring",
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
    why="Large inline tables consume tokens that should be progressively disclosed on demand.",
    fix="Move tables over 20 data rows into a referenced data file.",
    effort="authoring",
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
    why="Embedded base64 blobs waste tokens and carry no meaning the agent can read.",
    fix="Move the binary data into a referenced file.",
    effort="authoring",
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
# disclosure.* (progressive disclosure in practice — v0.2.0)
# =============================================================================

@rule(
    id="skills.disclosure.used", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#progressive-disclosure",
    summary=f"A body over {config.DISCLOSURE_BODY_LINES} lines splits detail into a sibling "
            f"references/ or scripts/ directory.",
    why="A very long body loaded all at once defeats progressive disclosure and floods the context window.",
    fix="Split detail into a references/ or scripts/ directory next to SKILL.md and link to it from the body.",
    effort="authoring",
)
def check_disclosure_used(doc: ParsedDocument, index: ArtifactIndex):
    body_lines = len(doc.body.splitlines())
    if body_lines <= config.DISCLOSURE_BODY_LINES:
        return None
    if index.tree is None:
        return None
    try:
        skill_dir = PurePosixPath(
            doc.path.resolve().relative_to(index.root).as_posix()
        ).parent
    except ValueError:  # pragma: no cover - a skill doc outside its own root
        return None
    # Answered from the listing, not the disk. A `references/` directory whose
    # files fall outside a fetch budget is still a `references/` directory —
    # and those files are the first thing a constrained fetch drops, so a
    # filesystem probe would accuse exactly the skills that did this right.
    # `RepoTree.resolves` records only directories that hold a visible file, so
    # an empty sibling still does not count as disclosure.
    has_sibling = any(
        index.tree.resolves(f"{skill_dir.as_posix()}/{name}")
        for name in ("references", "scripts")
    )
    if has_sibling:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.disclosure.used", severity=Severity.INFO,
        message=f"Body is {body_lines} lines (over {config.DISCLOSURE_BODY_LINES}) with no sibling "
                f"'references/' or 'scripts/' directory; split detail out for progressive disclosure.",
    )]


@rule(
    id="skills.disclosure.load-triggers", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#progressive-disclosure",
    summary="At least one file reference is introduced with a load condition (when/if clause).",
    why="References without load conditions get read eagerly or never, instead of when they are needed.",
    fix="Introduce each reference with a condition, e.g. 'Read references/setup.md when configuring a new environment.'.",
    effort="authoring",
)
def check_disclosure_load_triggers(doc: ParsedDocument):
    refs = _extract_references(doc.body)
    if not refs:
        return None
    lines = doc.body.splitlines()
    for i, line in enumerate(lines):
        if not any(ref in line for ref in refs):
            continue
        window = lines[max(0, i - 1): i + 2]
        if any(_LOAD_TRIGGER_RE.search(neighbor) for neighbor in window):
            return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="skills.disclosure.load-triggers", severity=Severity.INFO,
        message=f"None of the {len(refs)} file reference(s) is introduced with a load condition; "
                f"tell the agent when to read each file (e.g. 'Read X when ...').",
    )]


# =============================================================================
# scripts.* (bundled script hygiene — v0.2.0)
# =============================================================================

@rule(
    id="skills.scripts.non-interactive", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/best-practices",
    summary="Bundled scripts do not block on interactive prompts (input(), read -p, Read-Host, prompt()).",
    why="Agents cannot answer interactive prompts, so a blocking script hangs the session.",
    fix="Replace interactive prompts with command-line arguments or environment defaults.",
    effort="additive",
)
def check_scripts_non_interactive(doc: ParsedDocument):
    files = _script_files(doc)
    if files is None:
        return None
    skill_dir = doc.path.parent
    diags: list[Diagnostic] = []
    for path in files:
        text = _read_text_defensively(path)
        if text is None:
            continue
        hits = [p for p in _INTERACTIVE_PATTERNS if p in text]
        if hits:
            rel = path.relative_to(skill_dir).as_posix()
            diags.append(Diagnostic(
                rule_id="skills.scripts.non-interactive", severity=Severity.WARNING,
                message=f"Script '{rel}' appears interactive ({', '.join(hits)}); "
                        f"agents cannot answer prompts, so the session hangs.",
            ))
    return (1.0, []) if not diags else (0.0, diags)


@rule(
    id="skills.scripts.help", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/skill-creation/best-practices",
    summary="Every bundled script exposes a help surface (--help, argparse, click, commander, or yargs).",
    why="Scripts without a help surface force the agent to guess invocation syntax.",
    fix="Add --help output or use an argument parser (argparse, click, commander, yargs).",
    effort="additive",
)
def check_scripts_help(doc: ParsedDocument):
    files = _script_files(doc)
    if files is None:
        return None
    skill_dir = doc.path.parent
    diags: list[Diagnostic] = []
    for path in files:
        text = _read_text_defensively(path)
        if text is None:
            continue
        if not any(p in text for p in _HELP_PATTERNS):
            rel = path.relative_to(skill_dir).as_posix()
            diags.append(Diagnostic(
                rule_id="skills.scripts.help", severity=Severity.INFO,
                message=f"Script '{rel}' exposes no help surface "
                        f"(none of: {', '.join(_HELP_PATTERNS)}).",
            ))
    return (1.0, []) if not diags else (0.0, diags)


# =============================================================================
# references.*
# =============================================================================

@rule(
    id="skills.references.resolve", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.ERROR,
    source=RuleSource.ADVISORY, doc_url="https://agentskills.io/specification#file-references",
    summary="Relative file references in the body resolve to existing files in the repository.",
    why="A referenced file that does not exist sends the agent on a failing detour at load time.",
    fix="Fix the reference path or add the missing file.",
    effort="mechanical",
)
def check_references_resolve(doc: ParsedDocument, index: ArtifactIndex):
    """Existence check for body references, answered from the file listing.

    Existence is the whole claim. An earlier version also failed a reference
    for *leaving* the skill directory, on the theory that skills must be
    self-contained — but the Agent Skills spec's file-references section says
    only "use relative paths from the skill root" and "Keep file references one
    level deep from SKILL.md", neither of which forbids `../`. Sibling-skill
    cross-links and a single shared file two skills both read are ordinary,
    deliberate authoring; failing them told maintainers to duplicate content.

    Existence is decided against `index.tree`, never against the filesystem.
    A clone-free snapshot fetches only part of a large repository, and a
    `Path.is_file()` probe cannot tell "this file is not in the repository"
    from "this file was not fetched" — one real scan turned 356 perfectly good
    references into errors that way. The listing covers the whole repository
    at the pinned sha whatever the fetch budget was, so it answers the question
    the rule is actually asking.
    """
    refs = _extract_references(doc.body)
    if not refs:
        return None
    if index.tree is None:
        return None  # nothing to resolve against
    try:
        skill_dir = PurePosixPath(
            doc.path.resolve().relative_to(index.root).as_posix()
        ).parent
    except ValueError:  # pragma: no cover - a skill doc outside its own root
        return None

    base = skill_dir.as_posix()
    diags: list[Diagnostic] = []
    for ref in refs:
        if posixpath.isabs(ref):
            # An absolute path is machine-specific by construction: it cannot
            # be checked against a repository listing, and it does not travel
            # with the skill. No absolute path in the message either — the
            # checkout location must not leak into report output.
            diags.append(Diagnostic(rule_id="skills.references.resolve", severity=Severity.ERROR,
                                     message=f"Reference '{ref}' is an absolute path; "
                                             f"use a path relative to SKILL.md."))
            continue
        target = posixpath.normpath(posixpath.join(base, ref))
        if target.startswith(".."):
            continue  # leaves the repository; nothing in the listing to check
        if not index.tree.resolves(target):
            diags.append(Diagnostic(rule_id="skills.references.resolve", severity=Severity.ERROR,
                                     message=f"Referenced file does not exist in the scanned tree: '{ref}'."))
    return (1.0, []) if not diags else (0.0, diags)


@rule(
    id="skills.references.depth", pillar=Pillar.SKILLS, scope=RuleScope.SKILL,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://agentskills.io/specification#file-references",
    summary="File references stay one directory level deep from SKILL.md.",
    why="Deeply nested references break the flat one-level layout loaders expect from a skill directory.",
    fix="Move the referenced files to at most one directory level below SKILL.md.",
    effort="mechanical",
)
def check_references_depth(doc: ParsedDocument):
    """Nesting depth *below* SKILL.md, which is the whole of the spec's advice:
    "Keep file references one level deep from `SKILL.md`. Avoid deeply nested
    reference chains."

    A `../` reference is not deep — it is sideways, and the spec says nothing
    about it. This rule used to report those too, which made a link to a
    sibling skill look like a layout defect it is not.
    """
    refs = _extract_references(doc.body)
    if not refs:
        return None
    diags = []
    for ref in refs:
        if ref.startswith(".."):
            continue
        if _reference_depth(ref) > 1:
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
    why="Claude-only fields are silently ignored by VS Code/Copilot, so the skill behaves differently per platform.",
    fix="Check each flagged field against the compatibility matrix and remove it if cross-platform behavior matters.",
    effort="mechanical",
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
    why="Fields with unverified behavior in some agents may be ignored or misread there without notice.",
    fix="Verify the flagged fields against each target agent's documentation before relying on them.",
    effort="mechanical",
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
    why="Skills let agents load domain-specific procedures on demand instead of relying on one monolithic prompt.",
    fix="Add a skills/<name>/SKILL.md with name and description frontmatter for a recurring task.",
    effort="authoring",
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
    why="A skill that fails UTF-8 or YAML parsing is silently skipped by loaders.",
    fix="Fix the encoding or frontmatter YAML syntax reported in the diagnostic.",
    effort="mechanical",
    spec_quote="The `SKILL.md` file must contain YAML frontmatter followed by Markdown content.",
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
