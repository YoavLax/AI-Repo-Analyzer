# AI Readiness Analyzer v0.2.0 — "Fable" Refactor & Expansion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the v0.1.0 two-pillar prototype into a full eight-pillar,
multi-platform, multi-format analyzer — preserving every existing behavior and test
guarantee — and expand the rule catalog from 36 to ~95 high-precision deterministic rules.

**Architecture:** Keep the proven pure-function pipeline
(`fs.scan → discovery → parse → rules → scoring → report`) and extend each stage:
discovery becomes a declarative, platform-profile-driven artifact model (plan.md §5.1);
a new `probe` stage extracts deterministic repo facts (test/build/lint commands, CI,
hygiene); the registry gains `platforms`, `why`, `fix`, and `effort` metadata; scoring
gains platform sub-scores, weight profiles, and waivers; reporting becomes a package
with terminal/JSON/Markdown/SARIF renderers plus a ranked remediation plan.

**Tech Stack:** Python ≥3.11, PyYAML, click, pytest. Zero new runtime dependencies.
No network, no model calls, no wall-clock in the scoring path (see §D below for the one
quarantined exception: waiver expiry).

---

## 0. Ground rules (unchanged from plan.md §3 — the determinism contract)

1. Same input tree → byte-identical JSON. All iteration sorted, all paths
   `PurePosixPath`, no sets serialized unordered, no wall clock in scoring.
2. Every rule is a pure function returning `None` (not applicable) or
   `(satisfaction ∈ [0,1], [Diagnostic])`.
3. Advisory (heuristic) rules are never `ERROR` severity. Only objective,
   spec-verifiable failures may be `ERROR` (they trigger the grade cap).
   This *supersedes* the v1 catalog in plan.md §7 where it marked advisory rules `E`;
   the risk table in plan.md §13 already mandated this — the catalog below is normalized.
4. Existing public behavior is preserved: `airx analyze` flags, terminal layout shape,
   JSON keys of v0.1.0 remain (new keys are added, none removed), all 33 existing tests
   keep passing (score-threshold assertions may be re-validated against enriched
   fixtures, never weakened).

## 1. Scope

**In (v0.2.0):**
- Declarative discovery of the full artifact model: skills in all three roots,
  `*.instructions.md`, prompts, agents, hooks, MCP configs, `.claude/settings*.json`,
  `.claude/rules/*.md`, `CLAUDE.local.md`, nested `AGENTS.md`.
- New `probe.py`: languages, test/build/lint evidence, CI, setup/env hygiene facts.
- Six new rule modules: `quality`, `scoping`, `agents`, `verification`, `tooling`,
  `safety`; completion of `skills` (7 missing catalog rules) and `foundation`
  (sections coverage, imports, location).
- Scoring: platform sub-scores (`copilot`, `claude`, parity delta), weight profiles
  (`minimal`/`standard`/`enterprise` as data), `.airx.yml` waivers + ignores.
- Reporting: `report/` package — terminal, JSON (schema 0.2.0), Markdown, SARIF 2.1.0 —
  plus deterministic ranked remediation plan.
- CLI: `airx analyze` (new flags), `airx rules`, `airx compare`, `airx init`.
- Version 0.2.0; docs (README, CHANGELOG, CONTRIBUTING, generated docs/RULES.md) in English.

**Out (unchanged roadmap, plan.md §12):** GitHub Action, `airx fix`,
duplication shingling (`scoping.no-duplication`), `portability.platform-parity` as a
*rule* (the parity delta is reported in the score block instead — a rule cannot observe
the score being computed), hooks cross-platform/timeout deep checks, tiktoken, fleet/trend.

## 2. File map

```
src/airx/
├── __init__.py            MODIFY  __version__ = "0.2.0"
├── cli.py                 MODIFY  analyze flags; add rules/compare/init; exit codes 0/1/2/3
├── config.py              MODIFY  add PROFILES, secret shapes, curves, agent/prompt/settings
│                                  known-field sets, effort ranks; keep all vendored constants
├── model.py               MODIFY  add ArtifactKind, Artifact; extend RuleMeta fields via registry
├── fs.py                  KEEP    (unchanged)
├── parser.py              MODIFY  (Phase D: ParseError messages drop the absolute path —
│                                  the checkout location must not leak into report output)
├── tokenizer.py           KEEP    (unchanged)
├── patterns.py            CREATE  declarative discovery patterns per platform (plan.md §5.1)
├── discovery.py           MODIFY  full ArtifactIndex (backward-compatible fields kept)
├── probe.py               CREATE  deterministic repo facts (plan.md §5.2 subset)
├── airxfile.py            CREATE  .airx.yml loading: profile, ignore, waivers, thresholds
├── scoring.py             MODIFY  profiles, waivers, platform sub-scores, parity delta
├── remediation.py         CREATE  ranked remediation plan (gain / effort / rule_id)
├── report/
│   ├── __init__.py        CREATE  re-exports to_json, to_json_dict, to_terminal (compat)
│   ├── json.py            CREATE  schema 0.2.0
│   ├── terminal.py        CREATE  moved from report.py, extended
│   ├── markdown.py        CREATE  --format md
│   └── sarif.py           CREATE  --format sarif
└── rules/
    ├── __init__.py        MODIFY  import all 8 modules
    ├── registry.py        MODIFY  RuleMeta += platforms, why, fix, effort
    ├── foundation.py      MODIFY  +3 rules, backfill metadata
    ├── skills.py          MODIFY  +7 rules, backfill metadata
    ├── quality.py         CREATE  9 rules
    ├── scoping.py         CREATE  5 rules
    ├── agents.py          CREATE  11 rules
    ├── verification.py    CREATE  9 rules
    ├── tooling.py         CREATE  8 rules
    └── safety.py          CREATE  7 rules
tests/
    (all existing files KEEP; new: test_discovery.py, test_probe.py, test_airxfile.py,
     test_rules_quality.py, test_rules_scoping.py, test_rules_agents.py,
     test_rules_verification.py, test_rules_tooling.py, test_rules_safety.py,
     test_rules_foundation.py, test_report_formats.py, test_cli.py, test_remediation.py,
     plus new fixture repos listed per task)
docs/RULES.md              GENERATE via `airx rules --format md` (committed, dogfooded)
README.md / CHANGELOG.md / CONTRIBUTING.md   MODIFY (English)
plan.md                    KEEP (historical v1 design; README points here for vision)
.github/workflows/ci.yml   MODIFY  matrix 3.11–3.13, dogfood step
```

## 3. Core design changes

### 3.1 Model (`model.py`)

```python
class ArtifactKind(str, Enum):
    SKILL = "skill"                      # **/skills/<name>/SKILL.md
    ENTRYPOINT_COPILOT = "entrypoint_copilot"   # .github/copilot-instructions.md
    ENTRYPOINT_CLAUDE = "entrypoint_claude"     # CLAUDE.md | .claude/CLAUDE.md
    AGENTS_MD = "agents_md"              # AGENTS.md (root or nested)
    INSTRUCTIONS = "instructions"        # .github/instructions/**/*.instructions.md
    PROMPT = "prompt"                    # .github/prompts/**/*.prompt.md
    AGENT = "agent"                      # .github/agents/**/*.md | .claude/agents/**/*.md
    CLAUDE_RULE = "claude_rule"          # .claude/rules/**/*.md
    HOOKS = "hooks"                      # .github/hooks/*.json
    MCP = "mcp"                          # .mcp.json | .vscode/mcp.json | mcp.json
    CLAUDE_SETTINGS = "claude_settings"  # .claude/settings.json
    CLAUDE_SETTINGS_LOCAL = "claude_settings_local"
    CLAUDE_LOCAL_MD = "claude_local_md"  # CLAUDE.local.md

@dataclass(frozen=True)
class Artifact:
    kind: ArtifactKind
    rel_path: PurePosixPath
    platform: Platform
    doc: ParsedDocument | None      # parsed markdown, when applicable
    json_data: Any | None           # parsed JSON for hooks/mcp/settings (None on parse error)
    parse_error: str | None
```

`ParsedDocument`, `Severity`, `RuleSource`, `Platform`, `Pillar`, `Applicability`,
`Diagnostic`, `ParseError` stay as-is.

### 3.2 Patterns (`patterns.py`) — data, not code

One module-level tuple `DISCOVERY_PATTERNS: tuple[PatternSpec, ...]` where
`PatternSpec = (kind, platform, matcher)` and `matcher(rel: PurePosixPath) -> bool` is a
small pure function. Skills match `**/skills/<name>/SKILL.md` where the skills root is one
of `.github/skills`, `.claude/skills`, `.agents/skills`, or any `skills/` grandparent
(v0.1 behavior superset — the existing looser rule is kept so no fixture regresses).

### 3.3 Discovery (`discovery.py`)

`ArtifactIndex` keeps every v0.1 field (`skills`, `skill_parse_errors`,
`copilot_instructions`, `agents_md_paths`, `claude_md`, `claude_md_path`) and adds:

```python
artifacts: tuple[Artifact, ...]          # everything discovered, sorted by rel_path
instructions: tuple[Artifact, ...]       # kind == INSTRUCTIONS
prompts: tuple[Artifact, ...]
agents: tuple[Artifact, ...]
claude_rules: tuple[Artifact, ...]
hooks: tuple[Artifact, ...]
mcp: tuple[Artifact, ...]
claude_settings: Artifact | None
claude_settings_local_paths: tuple[PurePosixPath, ...]
claude_local_md_paths: tuple[PurePosixPath, ...]
agents_md_nested: tuple[PurePosixPath, ...]   # AGENTS.md not at repo root
tree: RepoTree                            # rules need the file list (globs, gitignore)
facts: RepoFacts                          # from probe.py
```

JSON artifacts (hooks/mcp/settings) are parsed with `json.loads`; a failure records
`parse_error` instead of raising — rules report it.

### 3.4 Probe (`probe.py`)

```python
@dataclass(frozen=True)
class RepoFacts:
    languages: tuple[tuple[str, int], ...]     # (extension, count) top 5, sorted by (-count, ext)
    package_scripts: tuple[str, ...]           # sorted package.json script names
    makefile_targets: tuple[str, ...]          # sorted top-level targets (regex ^([A-Za-z0-9_.-]+):)
    has_pytest: bool                           # pytest.ini | [tool.pytest] | conftest.py
    has_js_test_config: bool                   # jest/vitest config file present
    test_evidence: bool                        # any of the above, or tests/ dir, or scripts["test"]
    ci_workflows: tuple[PurePosixPath, ...]    # .github/workflows/*.yml|yaml + gitlab/azure/Jenkinsfile
    gitignore_lines: tuple[str, ...]           # stripped non-comment lines, in file order
    has_env_example: bool                      # .env.example | .env.template
    has_devcontainer: bool                     # .devcontainer/** | Dockerfile
    has_setup_script: bool                     # scripts/setup* | make target "setup" | bootstrap*
    version_pins: tuple[str, ...]              # found among .nvmrc, .tool-versions, rust-toolchain.toml,
                                               # requires-python (pyproject), .python-version
def probe(tree: RepoTree) -> RepoFacts
```

Reads only the files it names; every read is wrapped: unreadable/undecodable → treated as absent.
(All comparisons case-sensitive exact names; deterministic.)

### 3.5 Registry (`rules/registry.py`)

`RuleMeta` gains:

```python
platforms: tuple[Platform, ...] = (Platform.COPILOT, Platform.CLAUDE)  # universal default
why: str = ""       # one sentence: why this matters (traceable to plan.md §1)
fix: str = ""       # one actionable sentence
effort: str = "authoring"   # mechanical < additive < authoring < organizational
```

The `@rule` decorator accepts them as keywords. `all_rules()` unchanged (sorted by id).
`RULESET_VERSION = "0.2.0"` exported.

### 3.6 Scoring (`scoring.py`)

- `score(index, *, profile="standard", airx_config=None)` — profile selects
  `config.PROFILES[profile]` weights; unknown profile → `ValueError` (CLI maps to exit 2).
- **Waivers/ignores** (from `airxfile.AirxConfig`): ignored rule-id prefixes are skipped
  entirely (not registered in evaluations); waived rules evaluate but their satisfaction
  is forced to 1.0, diagnostics moved to a `waived` list, excluded from the error cap.
- **Platform sub-scores:** a rule contributes to platform P's score iff
  `P ∈ meta.platforms`. `ScoreCard` gains `copilot: float | None`,
  `claude: float | None`, `parity_delta: float | None` (None when a side has no rules).
  Same presence/quality/pillar aggregation, restricted to that platform's rules.
- Error cap, `_GRADE_RANK`, grade bands: unchanged.

### 3.7 `.airx.yml` (`airxfile.py`)

```python
@dataclass(frozen=True)
class Waiver:
    rule: str; reason: str; expires: str | None; approved_by: str | None
@dataclass(frozen=True)
class AirxConfig:
    profile: str | None; min_score: float | None; fail_on: str | None
    ignore: tuple[str, ...]; waivers: tuple[Waiver, ...]
def load(root: Path) -> AirxConfig | None      # None when file absent
```

Malformed `.airx.yml` → CLI exit 2 with a clear message. A waiver without `reason` is
invalid (exit 2). **Expiry quarantine (§0):** expiry is only evaluated when a date is
supplied (`--today YYYY-MM-DD`, or the `AIRX_TODAY` env var); without it, expiring
waivers stay active and the report carries a caveat. `governance.waiver-expired` fires
only when a date is available. The scoring path itself never reads the clock.

### 3.8 Remediation (`remediation.py`)

For each rule with `satisfaction < 1` and applicable: estimated
`score_gain = 100 · pillar_weight/Σscored_weights · split · rule_weight/Σbucket_weights · (1 − sat)`
where `split` is 0.40 (presence bucket) or 0.60 (quality bucket) and the Σ are over the
same bucket the rule was aggregated in. Sort by `(-score_gain, effort_rank, rule_id)`,
`effort_rank = {mechanical: 0, additive: 1, authoring: 2, organizational: 3}`.
Emit top 10: `{rank, rule_ids, score_gain (2dp), effort, action (meta.fix), paths}`.

### 3.9 Reports (`report/`)

- `report/__init__.py` re-exports `to_json`, `to_json_dict`, `to_terminal` — existing
  imports and tests keep working.
- **JSON** `schema_version: "0.2.0"`, adds `ruleset_version`, `profile`,
  `score.copilot/claude/parity_delta`, `inventory.artifacts` (kind, path, platform),
  `inventory.repo_facts`, per-finding `why`/`fix`/`effort`, `waivers`, `ignored_rules`,
  `remediation_plan`, `caveats`. All v0.1 keys preserved verbatim.
- **Terminal**: v0.1 layout + platform sub-score line + top-5 remediation section.
- **Markdown**: score header table, pillar table, findings grouped by severity,
  remediation table. Pure function of the JSON dict.
- **SARIF 2.1.0**: `runs[0].tool.driver = {name: "airx", version, informationUri}`,
  `driver.rules` from the catalog (id, shortDescription=summary, helpUri=doc_url),
  `results`: level error→"error", warning→"warning", info→"note";
  location = path + line (line 1 when unknown); repo-scope findings attach to
  the analyzed root as an artifactLocation with uriBaseId omitted.

### 3.10 CLI (`cli.py`)

```
airx analyze PATH [--format terminal|json|md|sarif] [-o FILE]
             [--fail-on error|warning|never] [--min-score N] [--profile NAME]
             [--platform copilot|claude|all] [--ignore PREFIX]... [--no-waivers]
             [--today YYYY-MM-DD] [--max-files N]
airx rules  [--format terminal|json|md]
airx compare OLD.json NEW.json          # exit 1 on regression (overall drop > 0.005
                                        #   or any new error-severity finding)
airx init   [--force]                   # scaffold .airx.yml (refuses to overwrite)
```

Exit codes: 0 pass · 1 gate failed (fail-on severity present, or overall < min-score)
· 2 input/config error · 3 unexpected internal error (top-level catch in `main`).
`--platform X` restricts scoring to rules tagged X (overall becomes that sub-score).
Precedence: CLI flag > `.airx.yml` > built-in default.

## 4. New rule catalog (exact specs)

Legend: Kind P/Q · Sev E/W/I · Src S/A · W weight · Platforms C=copilot, L=claude,
CL=both. Every rule also ships `why`, `fix`, `effort`. All text matching is
case-insensitive unless stated; all thresholds live in `config.py`.

### 4.1 `foundation.py` additions

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `foundation.sections.coverage` | Q | 6 | I | A | CL | Graded k/5 over entry-point headings+first-200-chars matching section keyword sets: overview `{overview, about, purpose, what is}`, techstack `{tech stack, stack, technologies, built with, framework, language}`, guidelines `{guideline, convention, style, standard, rule}`, structure `{structure, layout, organization, director, folder}`, resources `{script, command, tooling, resource, mcp}`. sat = k/5. N/A when no entry point. |
| `foundation.imports.resolve` | Q | 3 | E | S | L | Every `@path` import token in CLAUDE.md (regex `(?m)(?:^|\s)@([A-Za-z0-9_][A-Za-z0-9_./-]*)`) resolves to an existing file inside the repo. N/A when no imports. |
| `foundation.entrypoint.parses` | Q | 2 | E | S | CL | Entry points decode as UTF-8; if frontmatter fences exist, YAML parses. (Discovery already tolerates failures; this rule reports them.) N/A when no entry point. |

Backfill `platforms/why/fix/effort` on the 6 existing foundation rules
(copilot.entrypoint→C; claude.entrypoint, agentsmd.bridged→L; rest CL).

### 4.2 `skills.py` additions (completes the AgentEval port)

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `skills.name.no-namespace` | Q | 3 | E | S | CL | `name` contains `/` or `:` → error (plugins add prefixes automatically). N/A when name missing/non-string. |
| `skills.references.escape` | Q | 6 | E | S | CL | Split out of `references.resolve`: any reference resolving outside the skill dir (CWE-59). `references.resolve` keeps only the existence check (weight 5). |
| `skills.disclosure.used` | Q | 4 | I | A | CL | Body > 300 lines and no sibling `references/` or `scripts/` dir → 0. N/A ≤ 300 lines. |
| `skills.disclosure.load-triggers` | Q | 3 | I | A | CL | ≥ 1 reference and none introduced within ±1 line by `when`, `if`, `read .* (for\|when\|if)`, `run .* when` → 0. N/A without references. |
| `skills.scripts.non-interactive` | Q | 3 | W | A | CL | Files under sibling `scripts/` containing `input(`, `read -p`, `Read-Host`, `prompt(` → 0 with per-file diagnostics. N/A without scripts dir. |
| `skills.scripts.help` | Q | 2 | I | A | CL | Scripts expose `--help`/`argparse`/`click`/`commander`/`yargs` (substring). N/A without scripts. |
| `skills.coherence` | Q | 3 | I | A | CL | Description content words (non-stopword) < 15 → 0 ("too narrow"). sat 1 otherwise. |

Backfill `platforms/why/fix/effort` on all existing skills rules
(`dirname-match`, `no-namespace` → C-leaning but loaded by both: keep CL; compat rules CL).

### 4.3 `quality.py` (entry points + instructions files; N/A when none exist)

Directive = a line matching `^\s*[-*]\s+\S` with > 10 visible chars, in body text
(fenced code excluded). Rules needing directives are N/A below 3 directives.

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `quality.specificity.index` | Q | 6 | W | A | CL | Graded: concrete directives / directives, concrete = contains backtick, a path-shaped token (`[\w./-]+\.[A-Za-z0-9]{1,8}` or trailing `/`), a digit, or an `UPPER_SNAKE` token. sat = min(1, ratio/0.5). |
| `quality.rationale.present` | Q | 4 | W | A | CL | ratio of directives containing `because\|since\|to avoid\|so that\|otherwise\|to ensure\|to prevent`; sat = min(1, ratio/0.25). |
| `quality.examples.present` | Q | 4 | W | A | CL | ≥ 1 fenced code block, or a preferred/avoided pair (`instead of`, `don't … do`, `prefer … over`) anywhere in entry points. Binary. |
| `quality.no-obvious-rules` | Q | 3 | I | A | CL | Flags directives containing (normalized, lowercase) any of: `write clean code`, `use meaningful names`, `add comments`, `follow best practices`, `handle errors appropriately`, `keep it dry`, `use consistent indentation`, `write good code`. sat = 1 − flagged/directives (floor 0). |
| `quality.directive.atomicity` | Q | 2 | I | A | CL | Flags directives > 200 chars. sat = 1 − flagged/directives. |
| `quality.emphasis.calibrated` | Q | 2 | I | A | CL | Uppercase emphasis tokens (`IMPORTANT`, `YOU MUST`, `ALWAYS`, `NEVER`, `CRITICAL` — case-sensitive) on > 30% of directives → 0, else 1. N/A < 5 directives. |
| `quality.no-stale-markers` | Q | 2 | W | A | CL | `TODO`, `FIXME`, `TBD`, `XXX`, `<placeholder>`, `lorem ipsum` in any entry-point/instructions body → 0 with per-file diagnostics. |
| `quality.no-secrets` | Q | 4 | E | A | CL | High-precision shapes in **AI artifact files only**: `ghp_[A-Za-z0-9]{36}`, `github_pat_[A-Za-z0-9_]{22,}`, `sk-ant-[A-Za-z0-9-]{20,}`, `sk-[A-Za-z0-9]{40,}`, `AKIA[0-9A-Z]{16}`, `xox[bpoas]-[A-Za-z0-9-]{10,}`, `AIza[0-9A-Za-z_-]{35}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----`. ERROR is justified: objective, checksum-shaped. |
| `quality.links.resolve` | Q | 3 | W | A | CL | Relative markdown links in entry points/instructions resolve inside the repo. N/A without links. |

### 4.4 `scoping.py`

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `scoping.scoped-files.present` | P | 8 | W | A | CL | ≥ 1 `*.instructions.md`, or ≥ 1 `.claude/rules/*.md`, or a nested `AGENTS.md`. |
| `scoping.applyto.declared` | Q | 6 | E | S | C | Every `*.instructions.md` declares non-empty `applyTo` frontmatter. **Without it the file never auto-applies.** Per-file mean. |
| `scoping.applyto.matches` | Q | 4 | W | A | C | Each `applyTo` glob (comma-separated or YAML list) matches ≥ 1 file in the tree. Glob translator supports `**`, `*`, `?` (own regex translation, documented in code). |
| `scoping.applyto.not-universal` | Q | 3 | I | A | C | `applyTo: '**'` on > 1 file → 0. |
| `scoping.monolith` | Q | 5 | W | A | CL | Entry point > 250 lines **and** zero scoped files → 0. N/A when no entry point. |

### 4.5 `agents.py` (`.github/agents/**/*.md`, `.claude/agents/**/*.md`, `.github/prompts/**/*.prompt.md`)

Known agent fields: `{name, description, tools, model, target, argument-hint, color,
temperature, mode, handoffs, mcp-servers}`. Known prompt fields:
`{name, description, mode, model, tools, agent, argument-hint}`.

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `agents.present` | P | 5 | I | A | CL | ≥ 1 agent file. |
| `prompts.present` | P | 3 | I | A | C | ≥ 1 prompt file. |
| `agents.frontmatter.present` | Q | 4 | E | S | CL | Agent file has non-empty YAML frontmatter. Per-file. |
| `agents.name.required` | Q | 4 | E | S | L | `.claude/agents/*` must have non-empty string `name`. N/A for `.github/agents` (filename is the name). |
| `agents.description.required` | Q | 4 | E | S | CL | Non-empty string `description`. |
| `agents.description.quality` | Q | 4 | W | A | CL | Graded: reuse `skills.score_description` → sat = score/100. |
| `agents.description.person-voice` | Q | 2 | W | A | CL | Same first/second-person regexes as skills. |
| `agents.tools.declared` | Q | 5 | W | A | CL | `tools` field present (least privilege beats inherit-everything). |
| `agents.unknown-fields` | Q | 2 | W | A | CL | Fields outside the known set. |
| `agents.sizing` | Q | 3 | W | S | CL | ≤ 500 lines and ≤ 8000 tokens. |
| `prompts.frontmatter.valid` | Q | 3 | W | S | C | Prompt fields ⊆ known set; if `agent:` names a custom agent, an agent file with that name (frontmatter `name` or filename stem) exists. |

### 4.6 `verification.py`

Command-mention scan runs over entry-point + instructions bodies; a "documented test
command" = an inline-code span or fenced line containing one of: `pytest`, `npm test`,
`npm run <s>`/`yarn <s>`/`pnpm <s>` where `<s>` ∈ package_scripts, `make <t>` where
`<t>` ∈ makefile_targets, `go test`, `cargo test`, `dotnet test`, `mvn test`, `tox`.
Build and lint analogues use `{build, compile}` / `{lint, format, fmt, ruff, eslint,
prettier, flake8, black}` token sets against the same resolution logic.

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `verify.test-command.documented` | P | 7 | W | A | CL | A test command is documented **and** resolves against RepoFacts (see above). |
| `verify.build-command.documented` | P | 5 | W | A | CL | Same for build. N/A when repo has no build evidence (no package.json build script, no Makefile, no pyproject build-system? → still applicable; absence just scores 0 only when a build system exists — N/A otherwise). |
| `verify.lint-command.documented` | P | 4 | W | A | CL | Same for lint; N/A when no lint config detected (`.eslintrc*`, `eslint.config.*`, `ruff` in pyproject, `.prettierrc*`, `.golangci.yml`). |
| `verify.test-suite.exists` | P | 5 | W | A | CL | `facts.test_evidence`. |
| `verify.ci.exists` | P | 4 | W | A | CL | `facts.ci_workflows` non-empty. |
| `verify.loop.instructed` | Q | 5 | W | A | CL | Entry point instructs an iterate-until-green loop: `run the tests`, `until (it\|they) pass`, `verify`, `typecheck`, `re-run`, `iterate`. ≥ 2 distinct matches → 1; 1 match → 0.5; else 0. N/A without entry point. |
| `verify.hooks.present` | Q | 6 | I | A | CL | `.github/hooks/*.json` exists or `.claude/settings.json` has a `hooks` key. |
| `verify.hooks.schema` | Q | 5 | E | S | C | Each `.github/hooks/*.json`: valid JSON, `version: 1`, `hooks` object, each entry has `type: "command"` and `bash` or `powershell`. N/A without hook files. |
| `verify.evidence.instructed` | Q | 2 | I | A | CL | Entry point asks for evidence: `show the output`, `paste the (test )?output`, `include the command`, `evidence`. Binary. N/A without entry point. |

### 4.7 `tooling.py`

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `tooling.mcp.present` | P | 5 | I | A | CL | Any MCP config exists. |
| `tooling.mcp.valid` | Q | 5 | E | S | CL | Valid JSON; each entry under `mcpServers`/`servers` has `command` or `url`. N/A without MCP files. |
| `tooling.mcp.no-secrets` | Q | 6 | E | A | CL | No secret-shaped literal (same shapes as `quality.no-secrets`) and no `env` value that is a ≥ 16-char literal not using `${...}` indirection. N/A without MCP files. |
| `tooling.setup.script` | P | 4 | W | A | CL | `facts.has_setup_script` or `facts.has_devcontainer`. |
| `tooling.devcontainer` | Q | 3 | I | A | CL | `.devcontainer/` or `Dockerfile`. |
| `tooling.env.example` | Q | 3 | W | A | CL | If `.env` appears in `.gitignore` → an `.env.example`/`.env.template` must exist. N/A otherwise. |
| `tooling.versions.pinned` | Q | 3 | I | A | CL | `facts.version_pins` non-empty. |
| `tooling.scripts.documented` | Q | 4 | W | A | CL | If `len(package_scripts) ≥ 3` → entry point mentions ≥ 2 of them (inline code). N/A otherwise or without entry point. |

### 4.8 `safety.py`

Known top-level `.claude/settings.json` keys: `{permissions, env, hooks, model,
statusLine, includeCoAuthoredBy, cleanupPeriodDays, apiKeyHelper, defaultMode,
forceLoginMethod, enableAllProjectMcpServers, enabledMcpjsonServers,
disabledMcpjsonServers, awsAuthRefresh, awsCredentialExport, outputStyle, sandbox,
alwaysThinkingEnabled, companyAnnouncements, spinnerTipsEnabled}`.

| ID | K | W | Sev | Src | Pl | Check |
|---|---|---|---|---|---|---|
| `safety.local-files.not-committed` | Q | 6 | E | S | L | `CLAUDE.local.md` or `.claude/settings.local.json` present in the tree → 0 (they are personal files; committing them leaks local config). N/A when `.claude/`+CLAUDE.md absent entirely? No — always applicable (presence in tree is the violation); passes trivially when absent. |
| `safety.local-files.gitignored` | Q | 4 | W | A | L | If any Claude artifact exists → `.gitignore` contains both `CLAUDE.local.md` and `.claude/settings.local.json` entries (substring match on normalized lines). N/A when no Claude artifacts. |
| `safety.permissions.no-bypass` | Q | 6 | E | A | L | Committed settings do not set `defaultMode: "bypassPermissions"` or `"dangerouslySkipPermissions"` anywhere in `permissions`. N/A without settings. ERROR is justified: objective config value. |
| `safety.settings.valid` | Q | 4 | E | S | L | `.claude/settings.json` parses as JSON and top-level keys ⊆ known set. N/A without the file. |
| `safety.settings.no-secrets` | Q | 6 | E | A | L | `env` block values contain no secret shapes (same set). N/A without settings/env. |
| `safety.injection.surface` | Q | 4 | W | A | CL | Instruction/skill/agent bodies containing `curl … \| sh`, `wget … \| sh`, `iwr … \| iex`, or `npx <pkg>` without version pin inside a fenced block that the text tells the agent to run. Flag; sat 0 on any hit. |

*(Design change during Phase A: `governance.waiver-expired` is not a rule — rules see only
the `ArtifactIndex`, never `.airx.yml`. Expired waivers are handled by the scoring layer:
they stop waiving, surface in `ScoreCard.expired_waivers`, and render in every report.)*

Pillar weight totals stay per `config.PILLAR_WEIGHTS` (unchanged). With all 8 pillars now
scored, the standard profile denominators finally cover all 100 weight points.

## 5. Fixtures (new, minimal, committed)

| Fixture | Contents / purpose |
|---|---|
| `repo_scoped_ok` | copilot-instructions + `.github/instructions/py.instructions.md` with `applyTo: "**/*.py"` + a `.py` file → scoping green |
| `repo_scoped_missing_applyto` | instructions file without `applyTo` → `scoping.applyto.declared` error |
| `repo_agents_ok` | `.claude/agents/reviewer.md` with full frontmatter (name/description/tools) |
| `repo_agents_broken` | agent without frontmatter; prompt referencing a missing agent |
| `repo_verification_rich` | CLAUDE.md documenting `pytest`, `make lint`; Makefile with `lint:`; pytest.ini; `.github/workflows/ci.yml` |
| `repo_tooling_mcp` | valid `.mcp.json` (env indirection) + `.devcontainer/devcontainer.json` + `.nvmrc` |
| `repo_tooling_mcp_secret` | `.mcp.json` with `ghp_…36 chars` literal → error |
| `repo_safety_local_committed` | `.claude/settings.local.json` committed + settings.json with `defaultMode: bypassPermissions` → two errors |
| `repo_quality_rich` | entry point with sections, rationale, examples, specific directives |

*(Design change during Phase C: no separate `repo_full_stack` — `repo_good_skill` was
enriched into the everything-green A-grade fixture instead, which simultaneously restores
the pre-existing grade-cap test invariants under the full catalog. Its error twin
`repo_near_perfect_one_error` stays byte-identical except the one broken skill name.)*

Existing 8 fixtures unchanged. `repo_good_skill` / `repo_near_perfect_one_error` may gain
a documented-test-command line **only if** empirical scores drop below existing test
assertions (assertions themselves are not weakened).

## 6. Execution phases

- **Phase A (inline, sequential):** registry metadata → model/patterns/discovery →
  probe → airxfile → scoring → remediation → report package → CLI. Suite must be green
  (33 tests) after each module lands; run `pytest -q` at each checkpoint.
- **Phase B (Workflow fan-out, disjoint files):** 8 agents, one per rule module
  (quality, scoping, agents, verification, tooling, safety, skills-additions,
  foundation-additions). Each receives its §4 spec block verbatim and writes: the rule
  module (or in-place additions), its `test_rules_*.py` with satisfied/violated/N-A
  cases per rule, and its fixtures. Agents do not touch shared files
  (`rules/__init__.py`, `config.py` additions are pre-staged in Phase A).
- **Phase C (inline):** wire `rules/__init__.py`, re-run full suite, reconcile fixture
  score drift, dogfood run on this repo.
- **Phase D (Workflow):** adversarial review — finders (determinism, scoring integrity,
  rule correctness, test coverage) → per-finding verification → fixes.
- **Phase E (inline):** README/CHANGELOG/CONTRIBUTING rewrite, `docs/RULES.md`
  generation via `airx rules --format md`, CI workflow update, final full verification.

## 7. Acceptance checklist

- [x] All pre-existing 33 tests pass unmodified in intent (import paths preserved).
- [x] `pytest -q` fully green (310 tests); determinism test extended to all 16 fixtures.
- [x] Anti-gaming invariants hold with the full catalog (empty ≤ flawed; 20× skill
      duplication leaves the score unchanged at 96.92 — mean aggregation preserved).
- [x] `airx analyze tests/fixtures/repo_good_skill` → 96.9 / grade A, no errors.
- [x] `airx analyze . --format json | sarif | md | terminal` all render on this repo.
- [x] `airx rules --format md > docs/RULES.md` committed and in sync (CI diffs it).
- [x] JSON v0.1 keys unchanged; schema_version 0.2.0 (tests/test_report_formats.py).
- [x] No wall-clock reads in `src/airx/` (grep-verified; waiver expiry only via
      explicit `--today`/`AIRX_TODAY`).
- [x] README/CHANGELOG/CONTRIBUTING updated, English, accurate to shipped behavior.

## 8. Phase D adversarial-review outcome

A 25-agent find→verify workflow (5 finder dimensions, refute-oriented verifiers with
live reproductions) confirmed 13 unique defects; all are fixed and each is pinned by a
regression test in `tests/test_review_regressions.py`:

1. Skill script/disclosure rules re-walked the disk past `fs.scan`'s exclusions and
   followed symlinks out of the repo (CWE-59 reopened) — rule input now mirrors the
   scanned tree (`_visible_files`/`_is_scanned_file` in `skills.py`).
2. Link/import existence checks (`quality.links.resolve`, `foundation.imports.resolve`)
   probed the live filesystem (`.git`/`node_modules` sensitivity) — now resolved by
   membership in `index.tree.files`.
3. Absolute checkout paths leaked into `ParseError` messages and reference diagnostics —
   messages are path-free; discovery normalizes `OSError` text.
4. `safety.settings.valid` failed with WARNING-only diagnostics under an ERROR meta —
   unknown-key diagnostics are now ERROR, restoring "gate fires ⇒ error finding visible".
5. N/A presence rules aggregated as satisfaction-0 failures — the presence bucket now
   filters on `applicable`, mirrored in remediation.
6. `--platform` filtering corrupted the reported sub-scores/parity delta — sub-scores
   are computed from the unfiltered evaluation set before the filter applies.
7. Remediation `score_gain` missed the quality-ratio 0→1 fallback flip — gains are now
   exact re-aggregation deltas (satisfaction forced to 1.0, overall recomputed).
8. Glob translator: `**/` could not match zero segments (`**/*.py` missed root files) —
   translates to `(?:.*/)?`.
9. `agents.unknown-fields` crashed the whole analysis on non-string frontmatter keys —
   keys are `str()`-normalized before sorting.
10. Second-person voice regex could never fire (missing whitespace) — both person
    regexes fixed; skills and agents rules inherit the fix.
11. An unreadable Markdown artifact aborted the analysis with exit 3 — discovery now
    degrades it to a `parse_error` finding like JSON artifacts.
12. `airx compare` exited 3 instead of 2 on a report missing `score.grade` — grade
    access moved inside the validation block.
13. False "expiry was not evaluated" caveat when `--today` *was* supplied — the caveat
    is gated on `ScoreCard.today`; unescaped `|` in remediation text broke the Markdown
    Top-fixes table — table cells are GFM-escaped.
