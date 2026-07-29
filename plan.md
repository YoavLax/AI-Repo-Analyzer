# AI Readiness Analyzer — Design & Implementation Plan

> **Goal:** point the tool at a repository path (or Git URL) and get back a complete, reproducible
> analysis of how ready that repository is for AI coding agents — plus a single 0–100 score,
> per-platform sub-scores, and an actionable remediation list.
>
> **Non-negotiable constraint:** the analysis is **fully deterministic**. Same commit in → byte-identical
> report out. No LLM in the scoring path.
>
> **Platforms supported at v1:** GitHub Copilot (VS Code / CLI / cloud agent / code review) and Claude Code.
> The architecture keeps a neutral core so Cursor, Codex, Gemini CLI, etc. are additive.

---

## Table of contents

1. [Research summary — what "AI ready" actually means](#1-research-summary--what-ai-ready-actually-means)
2. [Product definition](#2-product-definition)
3. [Determinism contract](#3-determinism-contract)
4. [Architecture](#4-architecture)
5. [The Artifact Model](#5-the-artifact-model)
6. [Scoring model](#6-scoring-model)
7. [Rule catalog v1](#7-rule-catalog-v1)
8. [Reporting](#8-reporting)
9. [CLI & configuration](#9-cli--configuration)
10. [Repository layout](#10-repository-layout)
11. [Testing strategy](#11-testing-strategy)
12. [Delivery roadmap](#12-delivery-roadmap)
13. [Risks & mitigations](#13-risks--mitigations)
14. [Open questions](#14-open-questions)
15. [Source bibliography](#15-source-bibliography)

---

## 1. Research summary — what "AI ready" actually means

This section is the evidence base. Every rule in [§7](#7-rule-catalog-v1) traces back to a citation here.

### 1.1 Agent Skills open standard (agentskills.io)

The `SKILL.md` format is an **open standard** (originated at Anthropic, adopted by Claude Code,
VS Code/Copilot, Cursor, Codex, Gemini CLI, OpenCode, Goose, Kiro, Amp, and ~40 more clients).

**Directory shape**

```
skill-name/
├── SKILL.md          # required: YAML frontmatter + Markdown body
├── scripts/          # optional: executable code
├── references/       # optional: docs loaded on demand
└── assets/           # optional: templates, schemas, images
```

**Frontmatter schema**

| Field | Required | Constraint |
|---|---|---|
| `name` | yes | 1–64 chars, `[a-z0-9-]` only, no leading/trailing/consecutive hyphens, **must match parent directory name** |
| `description` | yes | 1–1024 chars, non-empty, states *what* it does **and when to use it** |
| `license` | no | license name or bundled file reference |
| `compatibility` | no | ≤500 chars, environment requirements |
| `metadata` | no | string→string map |
| `allowed-tools` | no | space-separated pre-approved tools (experimental) |

**Progressive disclosure — the three-tier budget**

| Tier | Loaded when | Budget |
|---|---|---|
| Metadata (`name` + `description`) | every session, all skills | ~100 tokens |
| Instructions (`SKILL.md` body) | on activation | **< 5,000 tokens**, **< 500 lines** |
| Resources (`scripts/`, `references/`, `assets/`) | on demand, only if referenced | unbounded |

**File references:** relative paths from skill root, **one level deep max**, must resolve.

**Description is the entire triggering mechanism.** Agents load only `name`+`description` at startup.
A weak description means the skill is invisible. Official guidance: imperative phrasing
("Use this skill when…" not "This skill does…"), focus on *user intent* not implementation, be
explicitly "pushy" about applicable contexts, stay concise.

**Authoring best practices worth scoring:**
- *Add what the agent lacks, omit what it knows* — cut anything the model already handles.
- *Design coherent units* — not too narrow (multi-skill thrash), not too broad (imprecise activation).
- *Provide defaults, not menus* — one recommended path + escape hatch.
- *Favor procedures over declarations* — reusable method, not a one-off answer.
- *Gotchas sections* — environment-specific facts that defy reasonable assumptions. Highest-value content.
- *Templates for output format*, *checklists for multi-step workflows*, *validation loops*,
  *plan-validate-execute* for destructive ops.
- *Scripts designed for agentic use* — no interactive prompts, `--help`, structured stdout,
  diagnostics to stderr, meaningful exit codes, idempotency, `--dry-run`, bounded output size.

### 1.2 GitHub Copilot custom instructions (github.blog "5 tips" + VS Code + GitHub docs)

The canonical `copilot-instructions.md` should contain five sections:

1. **Project overview** — elevator pitch: what the app is, who it's for, key features.
2. **Tech stack** — backend, frontend, data, APIs, test frameworks.
3. **Coding guidelines** — the non-obvious rules; conventions linters don't enforce.
4. **Project structure** — annotated directory map so the agent doesn't have to `ls` around.
5. **Resources** — scripts, MCP servers, tooling available for automation.

GitHub's own onboarding prompt sets an explicit limit: **"Instructions must be no longer than 2 pages"**
and **"broadly applicable to the entire project."**

VS Code's authoring guidance adds:
- Keep each instruction short, self-contained, one statement per line.
- **Include the reasoning** behind rules ("use `date-fns` instead of `moment.js` **because** moment.js
  is deprecated and increases bundle size") — the model handles edge cases better when it knows why.
- Show preferred/avoided patterns with **concrete code examples**.
- **Focus on non-obvious rules.** Skip what linters/formatters already enforce.
- Use multiple `*.instructions.md` files per topic, scoped with `applyTo`.

**Copilot artifact surface**

| Artifact | Location | Trigger |
|---|---|---|
| Repo instructions | `.github/copilot-instructions.md` | always-on |
| Agent-neutral instructions | `AGENTS.md` (root; nested experimental) | always-on |
| Claude-compat instructions | `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` | always-on |
| Path-scoped instructions | `.github/instructions/**/*.instructions.md` (`applyTo` glob) | glob / semantic match |
| Claude-format rules | `.claude/rules/**/*.md` (`paths` array) | glob match |
| Prompt files | `.github/prompts/*.prompt.md` | manual `/name` |
| Custom agents | `.github/agents/*.agent.md`, `.claude/agents/*.md` | manual selection / subagent |
| Agent skills | `.github/skills/<n>/SKILL.md`, `.claude/skills/<n>/SKILL.md`, `.agents/skills/<n>/SKILL.md` | automatic, description-matched |
| Hooks | `.github/hooks/*.json` | lifecycle events, deterministic |
| MCP servers | `.vscode/mcp.json`, `mcp.json`, `.mcp.json` | automatic / by name |

**Frontmatter schemas**

- `*.instructions.md`: `name?`, `description?`, `applyTo?` (glob; **if omitted, never auto-applies**)
- `.claude/rules/*.md`: `paths?` (array of globs; defaults to `**`)
- `*.prompt.md`: `description?`, `name?`, `argument-hint?`, `agent?`, `model?`, `tools?`
- `*.agent.md`: `description`, `name?`, `argument-hint?`, `tools?`, `agents?`, `model?`,
  `user-invocable?`, `disable-model-invocation?`, `target?`, `mcp-servers?`, `handoffs?`, `hooks?`
- `.claude/agents/*.md`: `name` (required), `description`, `tools` (comma string), `disallowedTools`
- `SKILL.md` (VS Code superset): + `argument-hint?`, `user-invocable?`, `disable-model-invocation?`, `context?` (`inline`|`fork`)

**Hard failure mode to detect:** in VS Code/Copilot, a skill whose `name` doesn't match its parent
directory, or contains invalid characters or a namespace prefix (`myorg/skill`, `myorg:skill`),
**silently fails to load**. Same for skills that never get a description good enough to trigger.

**Instruction precedence:** personal > repository > organization.

### 1.3 Claude Code best practices (code.claude.com)

Core thesis: **"Most best practices are based on one constraint: Claude's context window fills up
fast, and performance degrades as it fills."** Everything scoreable follows from that.

**CLAUDE.md guidance — directly scoreable**

> Keep it concise. For each line, ask: *"Would removing this cause Claude to make mistakes?"*
> If not, cut it. **Bloated CLAUDE.md files cause Claude to ignore your actual instructions.**

| ✅ Include | ❌ Exclude |
|---|---|
| Bash commands Claude can't guess | Anything derivable by reading the code |
| Code style rules that differ from defaults | Standard language conventions |
| Testing instructions & preferred test runners | Detailed API docs (link instead) |
| Repository etiquette (branch naming, PR conventions) | Info that changes frequently |
| Architectural decisions specific to your project | Long explanations or tutorials |
| Developer environment quirks (required env vars) | File-by-file codebase descriptions |
| Common gotchas / non-obvious behaviors | Self-evident advice ("write clean code") |

Memory docs add hard numbers: **target under 200 lines per CLAUDE.md file**; longer files consume
more context and reduce adherence. Use `.claude/rules/` with `paths` frontmatter to load
instructions only for matching files. Use **skills** (on-demand) for anything that isn't needed
every session. `@path/to/import` imports are for organization only — imported files still load at
launch, so they do **not** reduce context.

**Give the agent a way to verify its work.** Tests, build exit codes, linters, screenshot diffs,
Stop hooks, `/goal` conditions, verification subagents. A repo with no runnable check makes the
human the verification loop.

**Hooks are deterministic; instructions are advisory.**
> "Unlike CLAUDE.md instructions which are advisory, hooks are deterministic and guarantee the
> action happens."

If a rule must run every time (format after edit, block writes to `migrations/`), it belongs in a
hook, not prose. This is a first-class scoring signal.

**Skills vs CLAUDE.md:** "CLAUDE.md is loaded every session, so only include things that apply
broadly. For domain knowledge or workflows that are only relevant sometimes, use skills instead."

**Subagents** (`.claude/agents/*.md`) run in isolated context with their own tool allowlists.
Scoreable: presence, least-privilege `tools`, adversarial-review agent.

**AGENTS.md interop:** Claude Code reads `CLAUDE.md`, **not** `AGENTS.md`. The documented bridge is
a `CLAUDE.md` containing `@AGENTS.md` plus Claude-specific additions, or a symlink. A repo with
`AGENTS.md` and no `CLAUDE.md` bridge is invisible to Claude Code — high-value finding.

**Settings** (`.claude/settings.json`, project scope, committed): `permissions.allow/ask/deny`,
`hooks`, `env`, `sandbox`, `enabledPlugins`, `extraKnownMarketplaces`, `claudeMdExcludes`.
Security-relevant: `permissions.deny` for `Read(./.env)`, `Read(./secrets/**)`.
`.claude/settings.local.json` and `CLAUDE.local.md` **must be gitignored**.

**Common failure patterns** we can detect statically: over-specified CLAUDE.md, no verification
gate, unscoped instruction sprawl.

### 1.4 AgentEval (YoavLax/AgentEval) — the proven deterministic rule engine

AgentEval already implements a cross-agent quality gate for `SKILL.md` and `agent.md`. Its design is
the direct ancestor of this tool's rule engine and its rules should be **absorbed wholesale**.

**Architecture** — `parser.py` → `rules/*.py` → `result.py` → CLI/HTML/JSON reporters.
- `ParsedSkill(path, frontmatter, body, body_lines, raw_text)`; frontmatter split via regex handling
  CRLF and BOM (`utf-8-sig`), `yaml.safe_load`.
- `Diagnostic(rule, severity, message, line?, context?)`; `Severity ∈ {error, warning, info}`.
- `ValidationResult.valid = no ERROR diagnostics`.
- Rules are plain functions `(ParsedSkill) -> list[Diagnostic]`; parameterized rules are closures
  (`make_line_count_rule`, `make_token_estimate_rule`, `make_min_score_rule`, `make_strict_vscode_rule`).
- Exit codes: `0` clean, `1` errors, `2` input error.

**Thresholds (`config.py`)**

```python
MAX_BODY_LINES = 500          # sizing warning
MAX_TOKENS = 8000             # whole-file token warning
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
METADATA_TOKEN_BUDGET = 100   # frontmatter
BODY_TOKEN_BUDGET = 5000      # instructions
BLOAT_CODE_BLOCK_LINES = 50
BLOAT_TABLE_ROWS = 20
```

**Description quality scorer (0–100)** — the highest-value deterministic heuristic. Five dimensions:

| Dimension | Points | Logic |
|---|---|---|
| Action verbs | 25 | leading verb + ≥2 verbs → 25; leading only → 20; ≥2 non-leading → 15; 1 → 10; none → 0 |
| Trigger phrases | 25 | ≥2 patterns → 25; 1 → 20; weak signal → 10; none → 0 |
| Keyword density | 25 | content/total word ratio ≥0.6 → 25; ≥0.45 → 20; ≥0.3 → 15; else 5 |
| Specificity | 15 | vague-word ratio 0 → 15; ≤0.1 → 10; ≤0.2 → 5; else 0 |
| Length adequacy | 10 | 40–300 chars → 10; 300–500 → 7; <40 → 3; <20 or >500 → 0/3 |

Trigger patterns: `use (this) (skill) when`, `activate … for|when`, `run … when`, `invoke … when`,
`whenever (the) user mentions|asks|requests|needs|wants`, `make sure to use this skill`, `trigger(s|ed) when|for|by`.
Vague-word list: `tool, helper, utility, stuff, things, various, general, generic, simple, basic, easy,
nice, good, great, awesome, cool, helpful, useful, important, powerful, flexible, robust,
comprehensive, efficient, effective, handles`.

**Subtle traps AgentEval catches that we must keep:**
- **YAML type coercion** — `name: true` / `123` / `null` silently becomes `bool`/`int`/`None` under
  `safe_load`, corrupting all downstream checks. Explicit type rules.
- **YAML anchors/aliases** — `description: *name_anchor` silently copies a value and bypasses
  description validation.
- **First/second-person voice** in descriptions ("I can…", "You should…") — degrades routing.
- **XML/HTML tags** in descriptions.
- **Reserved words** `claude`, `anthropic` in skill names.
- **Reference escape (CWE-59 / path traversal)** — a reference resolving outside the skill directory
  via `..` or symlink is an **error**, not a warning. `Path.resolve()` + `is_relative_to(skill_dir)`.
- **Body bloat** — code blocks >50 lines, tables >20 data rows, base64 blobs (two-step detection:
  64+ base64-charset chars **and** mixed case, to avoid false positives on hex hashes).

**Cross-agent compatibility matrix** — fields that work in one agent and are ignored in another:

| Field | claude | vscode | codex | cursor |
|---|---|---|---|---|
| `name`, `description` | ✅ | ✅ | ✅ | ✅ |
| `version`, `author`, `tags`, `allowed-tools`, `user-invocable`, `context` | ✅ | ✅ | ? | ? |
| `model`, `disable-model-invocation`, `mode`, `hooks`, `agent`, `skills` | ✅ | **ignored** | ? | ? |

`CLAUDE_ONLY_FIELDS = {model, disable-model-invocation, mode, hooks, agent, skills}`.

**Agent-file rules** (`agent.py`) reuse description/sizing/disclosure rules but drop slug-name,
directory-match, and reference checks. Known agent fields: `{name, description, model, tools, applyTo}`.

**Known limitations to carry forward as explicit caveats:** token counts are estimates (~15% error
heuristic, ~5% with `tiktoken`); Codex/Cursor compat data is documentation-derived; description
scoring is lexical, not semantic; reference extraction only covers Markdown links and
`source:`/`file:`/`include:` directives.

### 1.5 AGENTS.md (agents.md, Linux Foundation / Agentic AI Foundation)

Open, format-free Markdown. No required fields. Read by 60k+ repos and a large agent ecosystem.
Nested files: "the closest AGENTS.md to the edited file wins." Popular sections: project overview,
build & test commands, code style, testing instructions, security considerations, PR instructions.

### 1.6 Synthesis — the eight pillars of AI readiness

Cross-cutting themes that appear in **every** source:

| # | Pillar | Core question | Primary sources |
|---|---|---|---|
| 1 | **Foundation** | Is there an always-on entry point, in a valid location, covering the essentials? | github.blog, VS Code, Claude memory |
| 2 | **Instruction quality** | Is it specific, reasoned, example-backed, non-obvious, and *short*? | Claude BP, VS Code tips |
| 3 | **Context scoping** | Is context loaded on demand rather than all at once? | Claude memory, `applyTo`/`paths` |
| 4 | **Skills & disclosure** | Do skills exist, conform to spec, and trigger reliably? | agentskills.io, AgentEval |
| 5 | **Agents & workflows** | Are there specialized agents/prompts with least-privilege tools? | VS Code agents, Claude subagents |
| 6 | **Verification & determinism** | Can an agent prove its work? Are must-run rules hooks, not prose? | Claude BP (verification, hooks) |
| 7 | **Tooling & environment** | MCP, CLI tools, setup scripts, devcontainer, discoverable commands | github.blog resources, Claude BP |
| 8 | **Safety, governance, portability** | Secrets excluded, permissions denied, local files gitignored, cross-platform parity | Claude settings, hooks security, compat matrix |

---

## 2. Product definition

### 2.1 One-liner

`airx analyze <repo>` → deterministic AI-readiness report + score for GitHub Copilot and Claude Code.

### 2.2 Primary users

| Persona | Job to be done |
|---|---|
| Platform / DevEx engineer | Roll out agent enablement across N repos, measure and track adoption |
| Repo maintainer | "What do I add to make Copilot/Claude actually good here?" |
| Engineering leadership | Portfolio dashboard: which repos are agent-ready |
| CI | Block PRs that regress agent config; annotate diffs |

### 2.3 Success criteria

- **Deterministic:** 1,000 consecutive runs on the same commit produce identical canonical output.
- **Fast:** < 5 s on a 50k-file repo (analysis is scoped to a bounded artifact set + cheap repo probes).
- **Actionable:** every deduction carries a rule ID, a file:line, a *why*, a *fix*, and a doc link.
- **Portable:** zero network access required for analysis; single binary/wheel; no API keys.
- **Honest:** clearly separates *spec* rules (objective) from *advisory* rules (best-practice opinion),
  and never claims semantic understanding it doesn't have.

### 2.4 Explicit non-goals for v1

- No LLM-based semantic judging in the score. (Optional, clearly-labelled, out-of-band `--llm-review`
  add-on may come in v2 — it will **never** affect the numeric score.)
- No trigger-rate evals (running live agents against query sets) — that's nondeterministic by nature.
  We approximate with the lexical description scorer. `airx eval` may wrap this in v2.
- Not a general code-quality/security scanner. We only assess AI-agent readiness.
- No auto-fix in v1 (v1.1 ships `airx fix --dry-run` for mechanical fixes only).

---

## 3. Determinism contract

This is the differentiating property, so it gets first-class engineering treatment.

### 3.1 Guarantees

**D1 — No model calls.** The scoring pipeline performs zero inference. Every rule is pure static analysis.

**D2 — No network.** Analysis runs offline. Fetching a remote repo happens in a separate, explicit
`ingest` phase before analysis, and the analyzed input is pinned to a commit SHA recorded in the report.

**D3 — Pure functions.** `analyze(Snapshot, RuleSet, Config) -> Report` is referentially transparent.
No wall-clock, no RNG, no environment reads, no locale dependence inside rules.

**D4 — Canonical ordering.** All file discovery output is sorted by POSIX-normalized relative path
using byte-wise ordering. All diagnostic lists are sorted by `(path, line, rule_id, message_hash)`.
Dict/JSON keys are emitted sorted.

**D5 — Input normalization.** Before parsing: strip UTF-8 BOM (`utf-8-sig`), normalize `\r\n` → `\n`,
Unicode NFC normalization for text comparisons, `str.casefold()` (not `.lower()`) for case-insensitive
matching. Non-UTF-8 files are reported as a diagnostic, never silently decoded.

**D6 — Pinned tokenizer.** Default is the **bundled heuristic estimator** (frozen algorithm, versioned).
`tiktoken` is opt-in via `--tokenizer=tiktoken` and, when used, its version is recorded in the report
and stamped into the output hash. Default never varies across machines.

**D7 — Versioned rule pack.** The report carries `ruleset_version` (semver) and `schema_version`.
Adding or reweighting a rule is a semver-minor/major bump. Historical scores remain reproducible via
`--ruleset-version=X.Y.Z`.

**D8 — Time and environment quarantine.** Timestamps, hostname, tool path, and duration live in a
`provenance` block that is **excluded from the canonical hash** and can be suppressed with
`--reproducible`. Score and diagnostics never contain them.

**D9 — Bounded traversal.** Deterministic caps: max files scanned, max file size, max symlink depth,
`.gitignore` honored via a vendored deterministic matcher (not the system `git`). Exceeding a cap
emits a diagnostic rather than silently truncating.

**D10 — Canonical hash.** Every report includes
`canonical_sha256` = SHA-256 of the canonically-serialized report minus `provenance`.
CI can assert stability.

### 3.2 Where non-determinism is legitimately needed — and how it's quarantined

| Capability | Why non-deterministic | Handling |
|---|---|---|
| `--verify-commands` (actually run declared build/test/lint) | executes arbitrary code, env-dependent | **Opt-in**, sandboxed, results land in a separate `verification_evidence` block, **excluded from score**, never in canonical hash |
| `--llm-review` (v2) | model sampling | opt-in, separate `advisory_review` block, excluded from score and hash, requires explicit `--i-understand-this-is-not-scored` |
| Git clone of remote URL | network | separate `ingest` phase, output pinned to SHA |

### 3.3 Enforcement

- `pytest` golden-file snapshot suite over a fixture corpus (§11).
- A `test_determinism.py` that runs analysis 50× with shuffled directory-listing order (via an
  injected FS adapter that randomizes `iterdir()`) and asserts identical `canonical_sha256`.
- A lint rule in CI forbidding `datetime.now`, `time.time`, `random`, `os.environ`, `uuid`, and
  `requests` imports inside `airx/rules/**`.

---

## 4. Architecture

### 4.1 Language & stack

**Python 3.11+.** Rationale:
- Direct lineage from AgentEval — rules, thresholds, and the description scorer port over 1:1.
- Best-in-class YAML/Markdown/glob ecosystem; `pip install`-able; trivial GitHub Action packaging.
- `pyproject.toml` + `uv` for fast, reproducible installs.

Dependencies (all pinned, minimal): `PyYAML`, `pathspec` (deterministic gitignore matching),
`click` (CLI), `jinja2` (HTML report, templates bundled — **no CDN assets**), `rich` (terminal, opt-out
via `--no-color`). Optional extra: `tiktoken`. Optional extra: `GitPython` for the ingest phase only.

Ship as: `pip install ai-repo-analyzer`, a `uvx`-runnable entry point, a Docker image, and a
composite GitHub Action.

### 4.2 Pipeline

```
                ┌────────────┐
 repo path/URL →│  1 INGEST  │→ Snapshot (pinned SHA, temp dir, provenance)
                └────────────┘
                       ↓
                ┌────────────┐
                │ 2 DISCOVER │→ ArtifactIndex  (sorted, typed, deduped)
                └────────────┘
                       ↓
                ┌────────────┐
                │  3 PARSE   │→ ParsedArtifact[]  (frontmatter, body, tokens, refs, AST-lite)
                └────────────┘
                       ↓
                ┌────────────┐
                │  4 PROBE   │→ RepoFacts (langs, test/build/lint config, CI, README, gitignore, secrets)
                └────────────┘
                       ↓
                ┌────────────┐
                │ 5 EVALUATE │→ Finding[]  (rule engine over ArtifactIndex × RepoFacts)
                └────────────┘
                       ↓
                ┌────────────┐
                │  6 SCORE   │→ ScoreCard (pillars, platforms, overall, grade)
                └────────────┘
                       ↓
                ┌────────────┐
                │  7 REPORT  │→ json / md / html / sarif / terminal   + exit code
                └────────────┘
```

### 4.3 Module responsibilities

| Module | Responsibility |
|---|---|
| `airx/ingest.py` | Resolve local path or clone `--depth 1` a URL; pin SHA; build `Snapshot(root, sha, is_dirty)` |
| `airx/fs.py` | Injectable FS adapter. Deterministic sorted traversal, gitignore via `pathspec`, size/count/symlink caps, safe read with BOM+CRLF normalization |
| `airx/discovery.py` | Path-pattern → `ArtifactKind` mapping for both platforms; produces `ArtifactIndex` |
| `airx/parse/` | `frontmatter.py` (BOM/CRLF-tolerant regex + `yaml.safe_load`), `markdown.py` (headings, code blocks, tables, links, base64), `jsonc.py` (settings/hooks/mcp), `tokens.py` (frozen heuristic + optional tiktoken) |
| `airx/probe/` | `languages.py`, `build.py` (npm/pnpm/make/gradle/cargo/dotnet/uv scripts), `tests.py`, `lint.py`, `ci.py`, `docs.py`, `hygiene.py` (gitignore, secrets patterns, devcontainer) |
| `airx/rules/` | Rule functions, one module per pillar. Pure. Registered via decorator into a versioned registry |
| `airx/scoring.py` | Pillar/platform/overall aggregation, waivers, profiles, grade bands |
| `airx/report/` | `json.py` (canonical), `markdown.py`, `html.py`, `sarif.py`, `terminal.py` |
| `airx/cli.py` | Click entry point, exit codes |
| `airx/config.py` | Thresholds, weights, profiles, `.airx.yml` loader |

### 4.4 Core data types

```python
@dataclass(frozen=True)
class Snapshot:
    root: Path
    commit_sha: str | None
    dirty: bool

class ArtifactKind(StrEnum):
    COPILOT_INSTRUCTIONS      # .github/copilot-instructions.md
    AGENTS_MD                 # AGENTS.md (root or nested)
    CLAUDE_MD                 # CLAUDE.md / .claude/CLAUDE.md
    CLAUDE_LOCAL_MD           # CLAUDE.local.md
    PATH_INSTRUCTIONS         # *.instructions.md
    CLAUDE_RULE               # .claude/rules/**/*.md
    PROMPT_FILE               # *.prompt.md
    CUSTOM_AGENT              # .github/agents/*.agent.md | .claude/agents/*.md
    SKILL                     # **/skills/<name>/SKILL.md
    SKILL_RESOURCE            # scripts/ references/ assets/ under a skill
    HOOKS_CONFIG              # .github/hooks/*.json
    CLAUDE_SETTINGS           # .claude/settings.json
    CLAUDE_SETTINGS_LOCAL     # .claude/settings.local.json
    MCP_CONFIG                # .mcp.json | .vscode/mcp.json | mcp.json
    PLUGIN_MANIFEST           # .claude-plugin/*.json

class Platform(StrEnum):
    COPILOT; CLAUDE; NEUTRAL

@dataclass(frozen=True)
class ParsedArtifact:
    path: PurePosixPath          # repo-relative, POSIX-normalized
    kind: ArtifactKind
    platforms: frozenset[Platform]
    frontmatter: Mapping[str, Any]      # {} when absent
    frontmatter_raw: str
    body: str
    raw_text: str
    line_count: int
    body_tokens: int
    metadata_tokens: int
    references: tuple[Reference, ...]
    headings: tuple[Heading, ...]
    code_blocks: tuple[CodeBlock, ...]
    tables: tuple[Table, ...]
    parse_error: str | None

@dataclass(frozen=True)
class Finding:
    rule_id: str            # e.g. "skill.name.directory-mismatch"
    pillar: Pillar
    severity: Severity      # error | warning | info
    source: RuleSource      # spec | advisory
    platforms: frozenset[Platform]
    satisfaction: float     # 0.0..1.0  (binary rules use 0/1)
    weight: int
    path: PurePosixPath | None
    line: int | None
    message: str
    why: str                # rationale, quoted/derived from docs
    fix: str                # concrete remediation
    doc_url: str
    waived: bool = False
    waiver_reason: str | None = None
```

### 4.5 Rule registration

```python
@rule(
    id="foundation.entrypoint.present",
    pillar=Pillar.FOUNDATION,
    kind=RuleKind.PRESENCE,
    weight=10,
    severity=Severity.ERROR,
    source=RuleSource.ADVISORY,
    platforms={Platform.COPILOT, Platform.CLAUDE},
    doc_url="https://code.visualstudio.com/docs/copilot/customization/custom-instructions",
    since="1.0.0",
)
def check_entrypoint_present(ctx: RuleContext) -> RuleOutcome: ...
```

`RuleOutcome` is `Applicable(satisfaction, findings)` or `NotApplicable(reason)`.
`NotApplicable` removes the rule's weight from its pillar denominator (see §6.3).

### 4.6 Extensibility for other agents

`ArtifactKind` + a `PlatformProfile` (path patterns, frontmatter schema, quirks like
"name must match dirname") are declarative. Adding Cursor (`.cursor/rules/`), Codex, or Gemini CLI
is a new profile plus a compat-matrix row — no core changes.

---

## 5. The Artifact Model

### 5.1 Discovery patterns (v1, exhaustive)

```yaml
copilot:
  entrypoint:      [".github/copilot-instructions.md"]
  instructions:    [".github/instructions/**/*.instructions.md"]
  prompts:         [".github/prompts/**/*.prompt.md"]
  agents:          [".github/agents/**/*.agent.md", ".github/agents/**/*.md"]
  skills:          [".github/skills/*/SKILL.md"]
  hooks:           [".github/hooks/*.json"]
  mcp:             [".vscode/mcp.json", "mcp.json"]

claude:
  entrypoint:      ["CLAUDE.md", ".claude/CLAUDE.md"]
  local:           ["CLAUDE.local.md"]
  rules:           [".claude/rules/**/*.md"]
  agents:          [".claude/agents/**/*.md"]
  skills:          [".claude/skills/*/SKILL.md"]
  settings:        [".claude/settings.json"]
  settings_local:  [".claude/settings.local.json"]
  mcp:             [".mcp.json"]
  plugin:          [".claude-plugin/marketplace.json", ".claude-plugin/plugin.json"]

neutral:
  agents_md:       ["AGENTS.md", "**/AGENTS.md"]
  skills:          [".agents/skills/*/SKILL.md"]
```

Nested monorepo discovery is on by default and reported per-package.

### 5.2 Repo facts probed (deterministic, config-file based)

| Fact | Evidence sought |
|---|---|
| Languages | file-extension histogram (top 5, ≥1% share) |
| Package manager | `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `uv.lock`, `poetry.lock`, `Cargo.lock`, `go.sum`, `*.csproj`, `pom.xml`, `build.gradle*` |
| Build command | `package.json#scripts.build`, `Makefile` targets, `Taskfile.yml`, `justfile`, `*.csproj`, `tox.ini`, `noxfile.py` |
| Test command | `scripts.test`, `pytest.ini`/`[tool.pytest]`, `jest.config.*`, `vitest.config.*`, `go test` presence, `Cargo.toml` `[dev-dependencies]` |
| Lint/format | `.eslintrc*`, `eslint.config.*`, `ruff.toml`/`[tool.ruff]`, `.prettierrc*`, `.editorconfig`, `rustfmt.toml`, `.golangci.yml` |
| Type checking | `tsconfig.json` (`strict`), `mypy.ini`, `[tool.pyright]` |
| CI | `.github/workflows/*.yml`, `azure-pipelines*.yml`, `.gitlab-ci.yml`, `Jenkinsfile` |
| Docs | `README*`, `CONTRIBUTING*`, `docs/**` |
| Env setup | `.devcontainer/`, `Dockerfile`, `docker-compose*`, `scripts/setup*`, `.env.example`, `.tool-versions`, `.nvmrc` |
| Hygiene | `.gitignore` entries for `CLAUDE.local.md`, `.claude/settings.local.json`, `.env` |
| Secret leakage | regex scan **of AI artifact files only** for AWS/GitHub/OpenAI/Anthropic/Azure key shapes, private-key PEM headers, and `Bearer` literals |

---

## 6. Scoring model

### 6.1 Pillar weights (profile: `standard`)

| # | Pillar | Weight |
|---|---|---|
| 1 | Foundation & entry point | **20** |
| 2 | Instruction quality | **15** |
| 3 | Context scoping & modularity | **12** |
| 4 | Skills & progressive disclosure | **15** |
| 5 | Agents & reusable workflows | **10** |
| 6 | Verification & determinism | **12** |
| 7 | Tooling & environment | **8** |
| 8 | Safety, governance & portability | **8** |
| | **Total** | **100** |

Alternate profiles ship as data, not code:

| Profile | Shift |
|---|---|
| `minimal` | Foundation 35, Instruction quality 25, Verification 15, Safety 10, Scoping 10, Tooling 5; Skills & Agents weighted 0 (reported, not scored) |
| `standard` | as above (default) |
| `enterprise` | Safety 15, Verification 18, Skills 15, Foundation 18, Quality 12, Scoping 10, Agents 7, Tooling 5 |

### 6.2 Presence/Quality split

Every pillar is split so that *absence is penalized* and *presence is graded* — you cannot score
well by having nothing.

```
pillar_score = 0.40 · presence_ratio + 0.60 · quality_ratio      (0..1)

presence_ratio = Σ(w_i · sat_i) / Σ(w_i)   over PRESENCE rules   (always applicable)
quality_ratio  = Σ(w_j · sat_j) / Σ(w_j)   over applicable QUALITY rules
                 (= 0 when presence_ratio == 0)
```

**Why this shape:** a repo with zero skills gets `presence=0` → skills pillar = 0. A repo with one
perfect skill gets a high score without being punished for having few. A repo with ten broken skills
gets `presence=1, quality≈0.1` → 0.46 of the pillar. Gaming by deletion is impossible.

### 6.3 Applicability

A QUALITY rule returning `NotApplicable` is removed from **both** numerator and denominator.
Example: `skill.references.resolve` is N/A when a skill has no references. This prevents penalizing
legitimate simplicity while still penalizing legitimate absence (handled by PRESENCE rules).

If **all** quality rules in a pillar are N/A but presence > 0, `quality_ratio` defaults to `1.0`
and the report annotates `quality_basis: "no applicable quality rules"`.

### 6.4 Graded satisfaction

Most rules are binary. Graded rules map a measured value onto `[0,1]` with a **piecewise-linear,
fully specified** curve — no magic constants in code, all in `config.py`:

```python
# Example: CLAUDE.md / copilot-instructions.md length (lines)
ENTRYPOINT_LINES = Curve(ideal=(30, 150), acceptable=(15, 200), zero_below=5, zero_above=400)
# → sat = 1.0 in [30,150]; linear taper to 0.5 at the acceptable bounds; to 0 at zero bounds
```

Graded rules in v1: entrypoint length, description quality score (0–100 → 0–1), body token budget,
metadata token budget, section coverage (k of 5), instruction specificity index, applyTo coverage
ratio, skill-count adequacy relative to repo size.

### 6.5 Platform sub-scores

Each rule declares `platforms`. Three scores are emitted:

- `score.copilot` — rules where `Platform.COPILOT ∈ platforms`
- `score.claude` — rules where `Platform.CLAUDE ∈ platforms`
- `score.overall` — all rules (the headline number)

Plus a **parity delta**: `abs(copilot − claude)`. A delta > 20 raises
`portability.platform-parity` (e.g. rich `AGENTS.md` with no `CLAUDE.md` bridge).

### 6.6 Grades

| Score | Grade | Label |
|---|---|---|
| 90–100 | A | Agent-native |
| 80–89 | B | Agent-ready |
| 70–79 | C | Agent-capable |
| 55–69 | D | Partially configured |
| 35–54 | E | Minimal |
| 0–34 | F | Not agent-ready |

Any `severity=error` finding caps the overall grade at **C**, regardless of arithmetic — a skill that
silently fails to load makes the config worse than not having it.

### 6.7 Waivers

`.airx.yml` may waive rules with a mandatory reason and optional expiry:

```yaml
version: 1
profile: standard
waivers:
  - rule: skills.present
    reason: "Domain knowledge lives in an internal plugin marketplace, not this repo."
    expires: "2027-01-01"
    approved_by: "platform-team"
```

Waived rules score `1.0` but are listed in a `waivers` report section with reasons. Expired waivers
are ignored and raise `governance.waiver-expired`. `--no-waivers` recomputes the unwaived score;
both numbers appear in the report (`score.overall`, `score.overall_unwaived`).

---

## 7. Rule catalog v1

Legend — **Src**: `S` = spec-derived (objective, from published format docs), `A` = advisory
(best-practice). **Kind**: `P` = presence, `Q` = quality. **Sev**: E/W/I.
`W` = weight within pillar.

### Pillar 1 — Foundation & entry point (20)

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `foundation.entrypoint.present` | P | 10 | E | A | At least one always-on entry point exists (`copilot-instructions.md` \| `AGENTS.md` \| `CLAUDE.md`) |
| `foundation.copilot.entrypoint` | P | 4 | W | S | `.github/copilot-instructions.md` or `AGENTS.md` present (Copilot) |
| `foundation.claude.entrypoint` | P | 4 | W | S | `CLAUDE.md` or `.claude/CLAUDE.md` present (Claude) |
| `foundation.agentsmd.bridged` | Q | 5 | W | S | If `AGENTS.md` exists without `CLAUDE.md`, a bridge (`@AGENTS.md` import or symlink) must exist — otherwise Claude Code cannot see it |
| `foundation.entrypoint.location` | Q | 3 | E | S | Entry point is in a location the tool actually reads (`.github/` for copilot-instructions; repo root or `.claude/` for CLAUDE.md) |
| `foundation.section.overview` | Q | 3 | W | A | Contains a project-overview section (heading match ∪ first-paragraph heuristic) |
| `foundation.section.techstack` | Q | 3 | W | A | Declares the tech stack |
| `foundation.section.guidelines` | Q | 3 | W | A | Declares coding guidelines |
| `foundation.section.structure` | Q | 3 | W | A | Documents project structure |
| `foundation.section.resources` | Q | 3 | W | A | Points to scripts / MCP servers / tooling |
| `foundation.entrypoint.length` | Q | 4 | W | A | Graded: ideal 30–150 lines; hard 0 above 400 (Claude: "target under 200 lines"; GitHub: "no longer than 2 pages") |
| `foundation.entrypoint.parses` | Q | 2 | E | S | File is valid UTF-8 and, if it has frontmatter, valid YAML |
| `foundation.entrypoint.no-conflict` | Q | 3 | W | A | No contradicting directives across multiple entry points (opposing normalized imperative pairs, e.g. "use tabs" vs "use spaces") |
| `foundation.imports.resolve` | Q | 2 | E | S | Every `@path` import in CLAUDE.md resolves and stays within the repo; depth ≤ 4 |

### Pillar 2 — Instruction quality (15)

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `quality.specificity.index` | Q | 6 | W | A | Graded. Ratio of *concrete* directives (contain a path, command in backticks, filename, numeric value, or named library) to total directives. Target ≥ 0.5 |
| `quality.rationale.present` | Q | 4 | W | A | ≥ 25% of directives include reasoning markers (`because`, `since`, `to avoid`, `otherwise`, `so that`) |
| `quality.examples.present` | Q | 4 | W | A | Contains ≥ 1 fenced code example, or an explicit preferred-vs-avoided pattern pair |
| `quality.no-obvious-rules` | Q | 3 | I | A | Flags directives matching a curated "linter-enforced / self-evident" corpus (`write clean code`, `use meaningful names`, `add comments`, `follow best practices`, `handle errors appropriately`, `keep it DRY`, `use consistent indentation`) |
| `quality.no-derivable-content` | Q | 3 | W | A | Flags file-by-file codebase descriptions and dependency dumps the agent can read itself (heuristic: >15 consecutive lines that are pure path listings, or a section mirroring `package.json` dependencies) |
| `quality.directive.atomicity` | Q | 2 | I | A | Flags bullets > 200 chars or containing ≥ 3 independent imperatives — split into separate instructions |
| `quality.emphasis.calibrated` | Q | 2 | I | A | Flags `IMPORTANT`/`YOU MUST`/`ALWAYS`/`NEVER` used on > 30% of directives (emphasis inflation destroys emphasis) |
| `quality.no-stale-markers` | Q | 2 | W | A | Flags `TODO`, `FIXME`, `TBD`, `<placeholder>`, `XXX`, `Lorem ipsum`, unedited template text in instruction files |
| `quality.no-secrets` | Q | 4 | E | A | No credential-shaped strings in any AI artifact file |
| `quality.commands.exist` | Q | 5 | W | A | Every ``` `command` ``` presented as a build/test/lint step maps to a real script/target in `package.json`/`Makefile`/`pyproject.toml`/etc. Catches drifted docs |
| `quality.links.resolve` | Q | 3 | W | A | Relative Markdown links in instruction files resolve within the repo |

### Pillar 3 — Context scoping & modularity (12)

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `scoping.scoped-files.present` | P | 8 | W | A | ≥ 1 `*.instructions.md` with `applyTo`, or ≥ 1 `.claude/rules/*.md` with `paths`, or nested `AGENTS.md` |
| `scoping.applyto.declared` | Q | 6 | E | S | Every `*.instructions.md` declares `applyTo`. **Without it the file never auto-applies** — a silent no-op |
| `scoping.applyto.matches` | Q | 4 | W | A | Every `applyTo` / `paths` glob matches ≥ 1 file in the repo (dead-glob detection) |
| `scoping.applyto.not-universal` | Q | 3 | I | A | Flags `applyTo: '**'` on more than one file — that's an always-on instruction wearing a scoped-file costume; consolidate into the entry point |
| `scoping.rules.frontmatter-valid` | Q | 3 | E | S | `.claude/rules/*.md` `paths` is an array of strings; brace-expansion budget (≤1000 expanded patterns) respected; no invalid bracket expressions |
| `scoping.monolith` | Q | 5 | W | A | Entry point > 250 lines **and** zero scoped files → content that should be path-scoped or moved to skills is loaded every session |
| `scoping.no-duplication` | Q | 4 | W | A | Near-duplicate directive blocks across entry point and scoped files (normalized shingling, Jaccard ≥ 0.8) |
| `scoping.monorepo.nested` | Q | 3 | I | A | In a detected monorepo (≥3 workspace packages), sub-packages have nested `AGENTS.md`/`CLAUDE.md`/scoped rules |

### Pillar 4 — Skills & progressive disclosure (15)

Absorbs the full AgentEval rule set. `<skill>` findings are per-file; the pillar aggregates by mean.

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `skills.present` | P | 8 | W | A | ≥ 1 `SKILL.md` in any recognized skills directory |
| `skills.name.required` | Q | 5 | E | S | `name` present |
| `skills.name.type` | Q | 4 | E | A | `name` is a string (catches YAML coercion of `true`/`123`/`null`) |
| `skills.name.max-length` | Q | 3 | E | S | ≤ 64 chars |
| `skills.name.charset` | Q | 5 | E | S | `^[a-z0-9-]+$` |
| `skills.name.hyphens` | Q | 3 | E | S | No leading/trailing hyphen; no `--` |
| `skills.name.reserved` | Q | 2 | E | A | Does not contain `claude` or `anthropic` |
| `skills.name.dirname-match` | Q | 6 | E | S | `name` == parent directory name. **VS Code silently drops mismatches** |
| `skills.name.no-namespace` | Q | 3 | E | S | No `/` or `:` prefix — plugins add the prefix automatically; manual prefixes silently fail |
| `skills.description.required` | Q | 5 | E | S | `description` present |
| `skills.description.type` | Q | 3 | E | A | `description` is a string |
| `skills.description.non-empty` | Q | 4 | E | S | Not blank/whitespace/null |
| `skills.description.max-length` | Q | 3 | E | S | ≤ 1024 chars |
| `skills.description.no-xml` | Q | 2 | E | A | No XML/HTML tags |
| `skills.description.person-voice` | Q | 3 | E | A | No first/second person ("I can…", "You should…") |
| `skills.description.quality` | Q | 8 | W | A | **Graded**: AgentEval 0–100 description score → satisfaction. Default floor 50 (`--min-desc-score`) |
| `skills.frontmatter.unknown-fields` | Q | 2 | W | A | Fields outside the known set |
| `skills.frontmatter.yaml-anchors` | Q | 3 | W | A | No YAML anchors/aliases — they silently copy values and bypass validation |
| `skills.budget.metadata` | Q | 3 | W | S | Frontmatter ≤ ~100 tokens |
| `skills.budget.body` | Q | 5 | W | S | Body ≤ 5,000 tokens |
| `skills.sizing.lines` | Q | 4 | W | S | File ≤ 500 lines |
| `skills.sizing.tokens` | Q | 3 | W | S | File ≤ 8,000 tokens |
| `skills.bloat.code-blocks` | Q | 2 | I | A | No code block > 50 lines in body |
| `skills.bloat.tables` | Q | 2 | I | A | No table > 20 data rows in body |
| `skills.bloat.base64` | Q | 2 | I | A | No base64 blob in body |
| `skills.references.resolve` | Q | 5 | E | A | Every relative reference exists on disk |
| `skills.references.escape` | Q | 6 | E | A | No reference resolves outside the skill dir (CWE-59 / traversal) |
| `skills.references.depth` | Q | 3 | W | S | References ≤ 1 level deep from `SKILL.md` |
| `skills.disclosure.used` | Q | 4 | I | A | Skills > 300 lines have a `references/` or `scripts/` dir — otherwise progressive disclosure isn't being used |
| `skills.disclosure.load-triggers` | Q | 3 | I | A | Referenced files are introduced with a *when* clause ("read X if…", "run X when…"), not a bare "see references/" |
| `skills.scripts.non-interactive` | Q | 3 | W | A | Bundled scripts have no interactive-prompt patterns (`input(`, `read -p`, `Read-Host`, `prompt(`) |
| `skills.scripts.help` | Q | 2 | I | A | Bundled scripts expose `--help` / `argparse` / `click` / `commander` |
| `skills.compat.claude-only` | Q | 2 | I | S | Flags `model`/`hooks`/`mode`/`agent`/`skills`/`disable-model-invocation` — ignored by VS Code/Copilot |
| `skills.compat.unverified` | Q | 1 | I | A | Flags fields with unverified Codex/Cursor behavior |
| `skills.coherence` | Q | 3 | I | A | Flags skills whose description enumerates ≥ 5 unrelated capability clusters (too broad) or < 15 content words (too narrow) |

### Pillar 5 — Agents & reusable workflows (10)

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `agents.present` | P | 5 | I | A | ≥ 1 custom agent (`.github/agents/`, `.claude/agents/`) |
| `prompts.present` | P | 3 | I | A | ≥ 1 prompt file (`.github/prompts/*.prompt.md`) |
| `agents.frontmatter.present` | Q | 4 | E | S | Agent file has YAML frontmatter |
| `agents.name.required` | Q | 4 | E | S | `name` present and non-empty (required in Claude format) |
| `agents.description.required` | Q | 4 | E | S | `description` present |
| `agents.description.quality` | Q | 4 | W | A | Graded, same 0–100 scorer (agents route by description too) |
| `agents.description.person-voice` | Q | 2 | E | A | Third person |
| `agents.tools.declared` | Q | 5 | W | A | `tools` explicitly declared — least privilege over inheriting everything |
| `agents.tools.least-privilege` | Q | 4 | W | A | Review/audit/plan-style agents (name/description match) declare read-only tool sets |
| `agents.tools.known` | Q | 3 | W | A | Declared tools are recognized names for the target platform |
| `agents.unknown-fields` | Q | 2 | W | A | Fields outside the known agent schema |
| `agents.sizing` | Q | 3 | W | S | ≤ 500 lines / 8,000 tokens |
| `agents.reviewer.present` | Q | 4 | I | A | A verification/adversarial-review agent exists (Claude BP: "add an adversarial review step") |
| `prompts.frontmatter.valid` | Q | 3 | W | S | `agent`/`model`/`tools` fields well-formed; referenced custom agent exists |
| `prompts.no-duplication` | Q | 2 | I | A | Prompt files don't inline instruction content that should be linked |
| `agents.handoffs.valid` | Q | 2 | W | S | Each `handoffs[].agent` resolves to an existing agent |
| `agents.claude-format.tools-string` | Q | 2 | W | S | `.claude/agents/*.md` `tools` is a comma-separated string, not a YAML array |

### Pillar 6 — Verification & determinism (12)

This pillar operationalizes Claude's #1 best practice: *give the agent a way to verify its work*, and
*use hooks for what must happen every time*.

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `verify.test-command.documented` | P | 7 | E | A | A test command is stated in an entry point **and** resolves to a real script/target |
| `verify.build-command.documented` | P | 5 | W | A | Build command stated and resolvable |
| `verify.lint-command.documented` | P | 4 | W | A | Lint/format command stated and resolvable |
| `verify.test-suite.exists` | P | 5 | W | A | Test files/config detected in the repo |
| `verify.ci.exists` | P | 4 | W | A | CI workflow present |
| `verify.loop.instructed` | Q | 5 | W | A | Entry point instructs the agent to run checks and iterate (`run the tests`, `verify`, `until it passes`, `typecheck when you're done`) |
| `verify.hooks.present` | Q | 6 | I | A | `.github/hooks/*.json` or `hooks` in `.claude/settings.json` |
| `verify.hooks.schema` | Q | 5 | E | S | `version: 1`; `hooks` object; each entry `type:"command"` with `bash` and/or `powershell`; valid event names |
| `verify.hooks.cross-platform` | Q | 3 | W | A | Hooks define **both** `bash` and `powershell` (or the repo is single-OS by evidence) |
| `verify.hooks.timeout` | Q | 3 | W | A | `timeoutSec` declared; ≤ 30 s (docs: keep under 5 s where possible) |
| `verify.hooks.scripts-exist` | Q | 4 | E | A | Hook script paths resolve inside the repo |
| `verify.hooks.no-inline-secrets` | Q | 4 | E | A | No credential literals in hook commands/env |
| `verify.hooks.enforce-must-rules` | Q | 4 | I | A | Directives phrased as absolutes (`ALWAYS run X before Y`, `NEVER write to Z`) that are enforceable as hooks but exist only as prose |
| `verify.ci.agent-gate` | Q | 4 | I | A | CI validates the agent config itself (e.g. an `agenteval`/`airx` step) — self-reinforcing readiness |
| `verify.evidence.instructed` | Q | 2 | I | A | Entry point asks the agent to show evidence (test output, command + result) rather than assert success |

### Pillar 7 — Tooling & environment (8)

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `tooling.mcp.present` | P | 5 | I | A | `.mcp.json` / `.vscode/mcp.json` / `mcp.json` present |
| `tooling.mcp.valid` | Q | 5 | E | S | Valid JSON; each server has a transport (`command`+`args` \| `url`) |
| `tooling.mcp.no-secrets` | Q | 6 | E | A | No literal tokens in MCP config — must use `${env:VAR}`/`${input:...}` indirection |
| `tooling.mcp.documented` | Q | 3 | I | A | Entry point mentions available MCP servers and what they're for |
| `tooling.setup.script` | P | 4 | W | A | A one-command setup path exists (`scripts/setup*`, `make setup`, `devcontainer`, documented install) |
| `tooling.devcontainer` | Q | 3 | I | A | `.devcontainer/` or `Dockerfile` present — reproducible agent environment |
| `tooling.env.example` | Q | 3 | W | A | `.env.example`/`.env.template` present when the code reads env vars |
| `tooling.versions.pinned` | Q | 3 | I | A | Toolchain version pinned (`.nvmrc`, `.tool-versions`, `requires-python`, `rust-toolchain.toml`) |
| `tooling.cli.declared` | Q | 3 | I | A | Entry point points the agent at CLI tools it should use (`gh`, `az`, `aws`, `kubectl`…) — most context-efficient integration path |
| `tooling.scripts.documented` | Q | 4 | W | A | Available scripts are enumerated in an entry point ("Point Copilot to available resources") |

### Pillar 8 — Safety, governance & portability (8)

| ID | Kind | W | Sev | Src | Check |
|---|---|---|---|---|---|
| `safety.local-files.gitignored` | Q | 6 | E | S | `CLAUDE.local.md` and `.claude/settings.local.json` are gitignored **and not committed** |
| `safety.local-files.not-committed` | Q | 6 | E | S | Neither file is tracked in the repo |
| `safety.permissions.deny-secrets` | Q | 5 | W | A | `.claude/settings.json` `permissions.deny` blocks `Read(./.env*)` / `Read(./secrets/**)` when such paths exist |
| `safety.permissions.no-bypass` | Q | 6 | E | A | Committed project settings do not set `defaultMode: bypassPermissions`, `disableAllHooks: true`, or `skipDangerousModePermissionPrompt: true` |
| `safety.settings.valid` | Q | 4 | E | S | `.claude/settings.json` is valid JSON and keys are recognized |
| `safety.settings.no-secrets` | Q | 6 | E | A | No credentials in `env` blocks of committed settings |
| `safety.injection.surface` | Q | 4 | W | A | Instruction/skill files that instruct the agent to fetch-and-execute remote content without pinning (`curl … \| sh`, unpinned `npx <pkg>`) |
| `portability.platform-parity` | Q | 6 | W | A | `abs(score.copilot − score.claude) ≤ 20` |
| `portability.skills.shared-location` | Q | 3 | I | A | Skills live in a location readable by both stacks, or are duplicated/symlinked for both |
| `portability.compat.documented` | Q | 2 | I | A | Platform-specific fields are used knowingly (repo declares a target, or provides both variants) |
| `governance.ownership` | Q | 3 | I | A | `CODEOWNERS` covers the AI config paths, or a doc names an owner |
| `governance.waiver-expired` | Q | 2 | W | A | No expired waivers in `.airx.yml` |
| `governance.license` | Q | 2 | I | A | Skills intended for sharing declare `license` |

**v1 rule count: ~130.** Every rule ships with `message`, `why` (traceable to §1), `fix`, and `doc_url`.

---

## 8. Reporting

### 8.1 Output formats

| Format | Flag | Purpose |
|---|---|---|
| Terminal | default | Human summary: score, grade, pillar bars, top 10 fixes |
| JSON | `--format json` | Canonical machine output; schema-versioned; `canonical_sha256` |
| Markdown | `--format md` | PR comment / job summary |
| HTML | `--html [file]` | Self-contained, offline, no CDN; pillar radar, per-file drill-down |
| SARIF | `--format sarif` | GitHub code scanning; inline PR annotations |

### 8.2 JSON schema (abridged)

```jsonc
{
  "schema_version": "1.0.0",
  "ruleset_version": "1.0.0",
  "target": { "path": "…", "commit_sha": "…", "dirty": false },
  "profile": "standard",
  "score": {
    "overall": 72.4, "overall_unwaived": 68.1, "grade": "C",
    "grade_capped_by": "skills.name.dirname-match",
    "copilot": 78.0, "claude": 61.2, "parity_delta": 16.8
  },
  "pillars": [
    { "id": "foundation", "weight": 20, "score": 0.84,
      "presence_ratio": 1.0, "quality_ratio": 0.73, "contribution": 16.8 }
  ],
  "inventory": {
    "artifacts": [ { "path": ".github/skills/deploy/SKILL.md", "kind": "SKILL",
                     "platforms": ["COPILOT","CLAUDE"], "lines": 210, "body_tokens": 1840 } ],
    "repo_facts": { "languages": ["python","typescript"], "test_command": "pytest",
                    "ci": [".github/workflows/ci.yml"] }
  },
  "findings": [
    { "rule_id": "skills.name.dirname-match", "pillar": "skills", "severity": "error",
      "source": "spec", "platforms": ["COPILOT"], "satisfaction": 0.0, "weight": 6,
      "path": ".github/skills/deploy/SKILL.md", "line": 2,
      "message": "Name 'deployer' does not match parent directory 'deploy'.",
      "why": "VS Code/Copilot silently fails to load skills whose name differs from the directory.",
      "fix": "Rename the directory to 'deployer' or change name to 'deploy'.",
      "doc_url": "https://agentskills.io/specification#name-field" }
  ],
  "waivers": [],
  "remediation_plan": [
    { "rank": 1, "score_gain": 6.4, "effort": "low", "rule_ids": ["…"], "action": "…" }
  ],
  "caveats": ["Token counts are estimates (heuristic tokenizer, ~15% error)."],
  "canonical_sha256": "…",
  "provenance": { "tool_version": "1.0.0", "generated_at": "…", "tokenizer": "heuristic-v1" }
}
```

### 8.3 Remediation plan — the actually-useful part

Findings are grouped and sorted by **score gain per unit effort**, deterministically:

```
priority_key = (-score_gain, effort_rank, rule_id)
effort_rank: mechanical(0) < additive(1) < authoring(2) < organizational(3)
```

Each entry names the exact file to create/edit and includes a ready-to-paste snippet from a bundled
template library (`airx/templates/`) — e.g. a scaffolded `copilot-instructions.md` with the five
sections, a `CLAUDE.md` `@AGENTS.md` bridge, a `SKILL.md` skeleton with a scored description, a
`.github/hooks/format.json`.

### 8.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | Passed (no errors; score ≥ `--min-score`, default 0) |
| 1 | Findings at `error` severity, or score below `--min-score` |
| 2 | Input error (bad path, unreadable repo, invalid config) |
| 3 | Internal error |

---

## 9. CLI & configuration

```
airx analyze <path|git-url> [options]

  --format {terminal,json,md,sarif}   Output format (default: terminal)
  --html [FILE]                       Also write a self-contained HTML report
  -o, --output FILE                   Write primary output to FILE
  --profile {minimal,standard,enterprise}
  --platform {copilot,claude,all}     Scope rules (default: all)
  --min-score N                       Fail below N (default: 0)
  --fail-on {error,warning,never}     Severity gate (default: error)
  --min-desc-score N                  Skill/agent description floor (default: 50)
  --ignore PREFIX                     Suppress rules by ID prefix (repeatable)
  --ruleset-version X.Y.Z             Pin the rule pack for historical comparability
  --tokenizer {heuristic,tiktoken}    Default: heuristic (deterministic across machines)
  --max-files N / --max-file-size N   Traversal caps
  --include-nested / --no-nested      Monorepo nested-artifact discovery (default: on)
  --no-waivers                        Ignore .airx.yml waivers
  --reproducible                      Omit provenance block; canonical output only
  --no-color / -q, --quiet

airx compare <report-a.json> <report-b.json>   # regression diff for CI
airx rules [--format json]                     # dump the rule catalog
airx init                                      # scaffold .airx.yml
airx fix --dry-run                             # v1.1: mechanical fixes only
```

`.airx.yml`:

```yaml
version: 1
profile: standard
platforms: [copilot, claude]
min_score: 70
fail_on: error
tokenizer: heuristic
thresholds:
  min_desc_score: 60
  entrypoint_max_lines: 200
ignore:
  - skills.compat.unverified
paths:
  exclude: ["vendor/**", "third_party/**"]
waivers:
  - rule: agents.present
    reason: "Single-purpose service; no specialized agent personas needed."
    expires: "2027-06-30"
    approved_by: "devex"
```

**GitHub Action** (composite, mirrors AgentEval's ergonomics):

```yaml
- uses: YoavLax/AI-Repo-Analyzer@v1
  with:
    path: .
    profile: standard
    min-score: 70
    fail-on: error
    comment-on-pr: true      # posts/updates a single sticky comment
    sarif-upload: true       # inline diff annotations
```

---

## 10. Repository layout

```
AI-Readiness-Analyzer/
├── plan.md
├── README.md
├── pyproject.toml
├── action.yml                          # composite GitHub Action
├── Dockerfile
├── src/airx/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py                       # thresholds, weights, profiles, curves
│   ├── ingest.py
│   ├── fs.py                           # injectable, deterministic FS adapter
│   ├── discovery.py
│   ├── model.py                        # dataclasses from §4.4
│   ├── parse/{frontmatter,markdown,jsonc,tokens}.py
│   ├── probe/{languages,build,tests,lint,ci,docs,hygiene,secrets}.py
│   ├── platforms/{copilot,claude,neutral}.py   # declarative PlatformProfile
│   ├── rules/
│   │   ├── registry.py                 # @rule decorator, versioned registry
│   │   ├── foundation.py
│   │   ├── quality.py
│   │   ├── scoping.py
│   │   ├── skills.py                   # AgentEval port
│   │   ├── agents.py
│   │   ├── verification.py
│   │   ├── tooling.py
│   │   └── safety.py
│   ├── scoring.py
│   ├── remediation.py
│   ├── templates/                      # scaffolds emitted by remediation plan
│   └── report/{json,markdown,html,sarif,terminal}.py
├── tests/
│   ├── fixtures/repos/                 # ~30 synthetic repos, committed
│   ├── golden/                         # expected canonical JSON per fixture
│   ├── unit/
│   ├── test_determinism.py
│   └── test_golden.py
└── docs/
    ├── rules/                          # one page per rule: why, fix, examples
    ├── scoring.md
    └── determinism.md
```

---

## 11. Testing strategy

| Layer | What |
|---|---|
| **Unit** | Every rule gets ≥ 3 cases: satisfied, violated, not-applicable. Parser edge cases: BOM, CRLF, no frontmatter, malformed YAML, YAML anchors, type coercion, non-UTF-8, empty file, frontmatter-only file |
| **Golden corpus** | ~30 committed fixture repos spanning: empty repo; README-only; perfect Copilot-only; perfect Claude-only; perfect dual; `AGENTS.md` with no bridge; broken skill (dirname mismatch); traversal-escape reference; 900-line CLAUDE.md; monorepo with nested configs; skill with base64 blob; hooks with inline secret; `.claude/settings.local.json` committed; MCP with hardcoded token; instructions with no `applyTo`; 20 skills all scoring < 30 |
| **Determinism** | 50 runs × shuffled FS ordering → identical `canonical_sha256`. Windows/Linux/macOS matrix asserts identical output. Locale matrix (`C`, `tr_TR.UTF-8` for the dotted-I trap, `de_DE.UTF-8`) |
| **Property** | Hypothesis: arbitrary frontmatter/body never crashes the parser; score always ∈ [0,100]; pillar contributions sum to overall ± 1e-9 |
| **Anti-gaming** | Deleting all skills must not raise the score. Duplicating a good skill 20× must not raise it above having 1. Padding the entry point must not raise it |
| **Cross-check** | Run against the AgentEval fixture set and assert identical verdicts on shared skill rules |
| **Performance** | Synthetic 50k-file repo, assert < 5 s and bounded memory |
| **Dogfood** | This repo scores ≥ 90 in its own CI |

---

## 12. Delivery roadmap

### Milestone 0 — Foundations (week 1)
Repo scaffold, `pyproject.toml`, CI matrix (3 OS × Python 3.11/3.12/3.13), `fs.py` with injectable
adapter + gitignore + caps, `parse/frontmatter.py`, `parse/tokens.py` (frozen heuristic), `model.py`,
determinism lint rule in CI.
**Exit:** `airx analyze` prints an artifact inventory; determinism test green.

### Milestone 1 — Skills engine (weeks 2–3) — ✅ implemented
Ported AgentEval in full: all frontmatter/name/description/sizing/disclosure/reference/compat
rules, the 0–100 description scorer, and the compat matrix, vendored into `airx/rules/skills.py`
and `airx/config.py` (open question 2, resolved: vendor). A first cut of pillar 1 (foundation
presence + length + structure) also landed alongside it in `airx/rules/foundation.py`, plus the
full `fs.py` → `discovery.py` → `scoring.py` → `report.py`/`cli.py` pipeline, so the tool is
runnable end-to-end today: `airx analyze <path>`. 33 tests cover unit rules, e2e fixture repos,
grade-cap behavior, and byte-for-byte determinism. Rule registry (`airx rules` CLI subcommand) is
not yet built — `all_rules()` exists but isn't exposed as a command.
**Exit:** ✅ met for the skills pillar; remaining milestones (2–6) still open.

### Milestone 2 — Foundation, quality & scoping (weeks 3–5)
Pillars 1–3. Section detection, specificity index, rationale/example detection, obvious-rule corpus,
duplication detection, `applyTo`/`paths` validation, dead-glob detection, `AGENTS.md`↔`CLAUDE.md`
bridge detection, import resolution.
**Exit:** meaningful scores on real-world repos; 15 golden fixtures.

### Milestone 3 — Verification, tooling, safety (weeks 5–7)
Pillars 6–8 + `probe/`. Command resolution against `package.json`/`Makefile`/`pyproject.toml`/etc.,
hooks schema validation, secrets scanning, permissions analysis, gitignore/tracked-file checks,
MCP validation, parity delta.
**Exit:** full 8-pillar score.

### Milestone 4 — Agents & workflows (week 7)
Pillar 5. Both agent formats, prompt files, handoff resolution, least-privilege heuristics.
**Exit:** ~130 rules live.

### Milestone 5 — Scoring, reporting, remediation (weeks 8–9)
Presence/quality aggregation, profiles, waivers, grade caps, all five reporters, template library,
ranked remediation plan, `airx compare`.
**Exit:** shippable reports; canonical hash stable.

### Milestone 6 — Distribution (week 10)
PyPI release, Docker image, composite GitHub Action with PR sticky comment + SARIF upload + job
summary, `docs/rules/` pages, README with screenshots.
**Exit:** `v1.0.0`.

### Post-v1 backlog
- `airx fix --dry-run` → `--apply` for mechanical fixes (dirname rename, add `applyTo`, add
  `timeoutSec`, gitignore local files, scaffold missing sections).
- `airx eval` — optional, explicitly-unscored trigger-rate harness per agentskills.io
  (train/validation split, N runs, trigger rate, overfitting guard).
- `--llm-review` advisory block (never scored).
- Additional platform profiles: Cursor, Codex, Gemini CLI, OpenCode, Amp.
- Fleet mode: `airx fleet <org>` → portfolio dashboard + trendlines from stored reports.
- VS Code extension surfacing findings as diagnostics on AI artifact files.
- Historical scoring: `airx trend --since <ref>` walking git history with a pinned ruleset.

---

## 13. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Formats evolve fast (VS Code shipped `.chatmode.md`→`.agent.md`, skills, hooks within a year) | Rules rot | Declarative `PlatformProfile`s; versioned rule packs; a documented quarterly "spec drift review"; `compat.unverified` severity stays `info` |
| Lexical heuristics ≠ semantic quality | False positives erode trust | Every heuristic rule is `advisory` + `info`/`warning`, never `error`. Advisory rules capped at ~40% of total weight. Findings state the heuristic used. `--ignore` is first-class |
| Score gaming (padding, duplication) | Metric loses meaning | Presence/quality split; duplication detection; length curves that penalize *both* directions; explicit anti-gaming test suite |
| Token estimates are approximate | Budget rules misfire | Heuristic is deliberately conservative; budget rules are `warning` not `error`; caveat printed in every report; `--tokenizer=tiktoken` available |
| Secret-scanning false positives | Noisy `error` findings | Scan **only** AI artifact files (tiny surface); high-precision shape regexes with checksum/prefix validation (`ghp_`, `sk-ant-`, `AKIA`+base32, PEM headers); entropy floor; `--ignore safety.*.no-secrets` |
| Monorepo explosion | Slow / noisy | Bounded traversal, per-package aggregation, `--no-nested` |
| Windows path/casing differences | Non-determinism | All paths normalized to `PurePosixPath`; casefold comparisons; explicit 3-OS CI matrix asserting identical hashes |
| Users expect an auto-fixer on day one | Disappointment | Remediation plan ships with paste-ready templates in v1; `airx fix` explicitly scheduled for v1.1 |
| Overlap with AgentEval | Confusion / duplicated effort | Position this as the superset: AgentEval = file-level linter, AI-Readiness-Analyzer = repository-level assessment that *embeds* it. Credit explicitly; keep verdict parity via cross-check tests |

---

## 14. Open questions

1. **Package/CLI name.** `airx`? `ai-readiness`? `arai`? Needs a PyPI availability check.
2. **AgentEval relationship — RESOLVED: vendor.** Implemented in `airx/config.py` (thresholds,
   compat matrix) and `airx/rules/skills.py` (all frontmatter/description/sizing/disclosure/
   references/compat rule logic, plus the 0–100 description scorer), each ported and credited
   inline rather than imported as a dependency on the `agenteval` package. This keeps the ruleset
   versioned with this repository's report schema and immune to upstream threshold changes.
3. **Should `minimal` profile zero out Skills/Agents**, or keep them at low weight? Zeroing risks
   signalling that skills don't matter; low weight risks unfairly penalizing tiny repos.
4. **Grade cap on any error — RESOLVED: any unwaived error-severity finding caps the grade at C.**
   Implemented in `airx/scoring.py` (`config.ERROR_CAPS_GRADE_AT`): the cap only ever pulls an A/B
   raw grade down to C — it never upgrades an already-worse grade (D/E/F) — enforced by
   `_GRADE_RANK` comparison and covered by `tests/test_scoring_grade_cap.py`, including a
   dedicated fixture (`repo_near_perfect_one_error`) proving the cap actually engages rather than
   being a no-op on an already-low score. The narrower "silent-load-failure only" alternative
   below was considered and rejected for v1 in favor of the simpler, more conservative blanket
   rule; it remains an option to relax later if the blanket cap proves too harsh in practice:
   cap only on errors that cause *silent load failure* (dirname mismatch, missing `applyTo`,
   invalid charset), which is the truly dangerous class.
5. **Nested/monorepo aggregation** — mean across packages, min, or weighted by package size?
6. **Do we score `.github/workflows` agentic workflows** (GitHub Agentic Workflows) as a Pillar 6
   signal in v1, or defer?
7. **Report storage** for trends — leave to the consumer, or ship a tiny `airx store` SQLite backend?

---

## 15. Source bibliography

**Primary specs**
- Agent Skills — Overview, Specification, Best practices, Optimizing descriptions, Evaluating skills,
  Using scripts — `https://agentskills.io/` (+ `/llms.txt`)
- AGENTS.md — `https://agents.md/` (Agentic AI Foundation / Linux Foundation)

**GitHub Copilot**
- "5 tips for writing better custom instructions for Copilot" — `https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/`
- Custom instructions in VS Code — `https://code.visualstudio.com/docs/copilot/customization/custom-instructions`
- Agent Skills in VS Code — `https://code.visualstudio.com/docs/copilot/customization/agent-skills`
- Prompt files in VS Code — `https://code.visualstudio.com/docs/copilot/customization/prompt-files`
- Custom agents in VS Code — `https://code.visualstudio.com/docs/copilot/customization/custom-agents`
- About agent skills — `https://docs.github.com/en/copilot/concepts/agents/about-agent-skills`
- About hooks for GitHub Copilot — `https://docs.github.com/en/copilot/concepts/agents/hooks`
- Copilot customization cheat sheet — `https://docs.github.com/en/copilot/reference/customization-cheat-sheet`

**Claude Code**
- Best practices — `https://code.claude.com/docs/en/best-practices`
- Memory (CLAUDE.md, `.claude/rules/`, auto memory) — `https://code.claude.com/docs/en/memory`
- Settings (permissions, hooks, sandbox, plugins, precedence) — `https://code.claude.com/docs/en/settings`

**Reference implementation**
- AgentEval — `https://github.com/YoavLax/AgentEval`
  (`src/agenteval/rules/{frontmatter,description,disclosure,sizing,references,compat,agent,__init__}.py`,
  `config.py`, `result.py`, `parser.py`, `README.md`)

**Community corpora (for fixture sourcing and rule calibration)**
- `github/awesome-copilot`
- `anthropics/skills`
