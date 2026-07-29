# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) for its
report schema and ruleset (see `plan.md` section 3, determinism guarantee D7).

## [Unreleased]

## [0.2.0] — 2026-07-29 — "Fable"

Full-catalog release: every pillar scored, multi-platform sub-scores, waivers,
four report formats, and three new subcommands. Design and rationale in
[`plan-v2-fable.md`](plan-v2-fable.md); report `schema_version` and
`ruleset_version` are both `0.2.0`. All v0.1.0 JSON keys are preserved — v0.2.0
only adds keys.

### Added
- **Six new rule pillars** (58 new rules; catalog now 94 across all 8 pillars):
  - *Instruction quality* (9): specificity index, rationale/example detection,
    obvious-rule and stale-marker flags, emphasis calibration, high-precision
    credential-shape scanning in AI artifact files, relative-link resolution.
  - *Context scoping* (5): `*.instructions.md` discovery, the missing-`applyTo`
    silent no-op trap, dead-glob detection, universal-glob flag, monolith check.
  - *Agents & prompts* (11): frontmatter/name/description validation for
    `.github/agents/` and `.claude/agents/`, description quality scoring,
    least-privilege `tools` declaration, prompt-file field validation with
    agent-reference resolution.
  - *Verification* (9): documented-and-resolvable test/build/lint commands
    (checked against `package.json`/`Makefile`/`pyproject.toml` evidence),
    test-suite/CI presence, iterate-until-green and show-evidence instructions,
    hooks presence and schema validation.
  - *Tooling* (8): MCP config presence/validity/secret-indirection, setup
    script, devcontainer, `.env.example` hygiene, version pinning, script
    documentation coverage.
  - *Safety* (6): committed personal files (`CLAUDE.local.md`,
    `.claude/settings.local.json`), gitignore coverage, permission-bypass
    settings, settings schema and secret scanning, fetch-and-execute
    (`curl | sh`) injection surface.
- **Skills pillar completion** (+7 rules): namespace-prefix trap, dedicated
  CWE-59 reference-escape rule, progressive-disclosure usage and load-trigger
  checks, bundled-script interactivity/help checks, description coherence.
- **Foundation pillar completion** (+3 rules): five-section coverage (graded),
  `@path` import resolution in `CLAUDE.md`, entry-point parse validation.
- **Declarative artifact model** (`patterns.py`): skills in `.github/skills`,
  `.claude/skills`, `.agents/skills`; instructions, prompts, agents, Claude
  rules, hooks, MCP configs, settings, local files, nested `AGENTS.md`.
- **Repo facts probe** (`probe.py`): languages, package scripts, Makefile
  targets, test/lint/build evidence, CI workflows, gitignore hygiene,
  devcontainer/setup/env/version-pin detection — all deterministic.
- **Platform sub-scores**: every rule is tagged `copilot`/`claude`; reports
  carry `score.copilot`, `score.claude`, and the parity delta.
  `--platform copilot|claude` restricts scoring to one side.
- **Weight profiles** (`standard`, `minimal`, `enterprise`) as pure data;
  `--profile` flag and `.airx.yml` setting.
- **Waivers & ignores** (`.airx.yml`): waived rules score 1.0, stay visible in
  a `waivers` report section, and are excluded from the grade cap; expiry is
  evaluated only against an explicit `--today`/`AIRX_TODAY` date so the
  scoring path never reads the clock. `--ignore PREFIX` and the `ignore:` list
  drop rules from the denominator entirely.
- **Report formats**: Markdown (`--format md`) for PR comments and SARIF 2.1.0
  (`--format sarif`) for GitHub code scanning, alongside the existing terminal
  and JSON renderers (now a `report/` package).
- **Ranked remediation plan** in every report: estimated score gain per fix,
  computed exactly from the aggregation formula, ranked by
  `(-gain, effort, rule_id)`.
- **New subcommands**: `airx rules` (catalog as terminal/JSON/Markdown —
  generates `docs/RULES.md`), `airx compare old.json new.json` (regression
  diff, exit 1 on score drop or new errors), `airx init` (scaffold
  `.airx.yml`).
- **Rule metadata**: every rule now carries `platforms`, `why`, `fix`, and
  `effort`, surfaced in JSON findings and the remediation plan.
- Exit codes: `0` pass, `1` gate failed, `2` input/config error, `3` internal
  error.
- Test suite grown from 33 to 310 tests; 8 new fixture repos; determinism
  checks extended to all fixtures; a dedicated adversarial-review regression
  suite (`tests/test_review_regressions.py`); CI matrix now includes Python
  3.13 and a `docs/RULES.md` sync check.

### Fixed (found by the pre-release adversarial review)
- Skill script/disclosure rules no longer read files `fs.scan` excludes or
  follow symlinks outside the repository (CWE-59); link/import resolution now
  checks membership in the scanned tree instead of probing the live
  filesystem, so `.git`/`node_modules` contents can no longer change a score.
- Absolute checkout paths no longer leak into parse-error messages or
  reference diagnostics (reports from different clones are comparable).
- N/A presence rules no longer count as failures in pillar aggregation;
  `--platform` filtering no longer corrupts the reported platform sub-scores;
  remediation gains are exact re-aggregation deltas.
- `**/` globs match zero path segments (`**/*.py` now matches root files);
  non-string frontmatter keys and unreadable Markdown artifacts no longer
  crash the analysis; second-person voice detection actually fires;
  `airx compare` returns exit 2 (not 3) on malformed reports; Markdown table
  cells escape `|`; the waiver-expiry caveat only appears when no evaluation
  date was supplied.

### Changed
- `report.py` split into the `airx.report` package (`terminal`, `json`,
  `markdown`, `sarif`); the old imports keep working.
- A pillar whose rules are all not-applicable is now reported as *not scored*
  and excluded from the weighted overall, instead of contributing a vacuous
  100% (the absence itself is already penalized by presence rules elsewhere).
- Advisory-severity policy from `plan.md` §13 is now enforced in code: the
  registry rejects advisory rules with `error` severity unless they are on the
  explicit objective-check allowlist.
- The `repo_good_skill` fixture was enriched into a full-stack A-grade
  repository so the grade-cap proof fixtures remain meaningful under the full
  catalog (its error twin differs only in the one broken skill name).

### v0.1.0 (initial commit)

### Added
- Core pipeline: `fs.py` (deterministic, bounded, symlink-free traversal) →
  `discovery.py` → `parser.py` → `rules/` → `scoring.py` → `report.py` / `cli.py`.
- **Skills pillar**: 30 rules vendored and adapted from
  [AgentEval](https://github.com/YoavLax/AgentEval) covering `SKILL.md`
  frontmatter validation, the 0–100 description-quality scorer, progressive
  disclosure token budgets, bloat detection, file-reference resolution with
  path-traversal protection, and cross-agent compatibility notes.
- **Foundation pillar** (partial): entry-point presence for GitHub Copilot
  (`.github/copilot-instructions.md`, `AGENTS.md`) and Claude Code
  (`CLAUDE.md`), the `AGENTS.md` → `CLAUDE.md` bridge check, a length curve,
  and a section-structure heuristic.
- Presence/quality pillar scoring model (`config.PRESENCE_WEIGHT` /
  `QUALITY_WEIGHT`) with anti-gaming guarantees (deleting artifacts cannot
  score higher than having a flawed one).
- Grade bands A–F, with any unwaived **error**-severity finding capping the
  overall grade at **C** (never upgrading a worse grade).
- `airx analyze <path>` CLI: terminal and JSON report formats, `--fail-on`
  exit-code gating.
- 33 tests: parser edge cases, individual rule units, 8 fixture repos,
  grade-cap proof, and byte-for-byte determinism checks.

### Not yet implemented (as of 0.1.0; addressed in 0.2.0 except where noted)
Quality, scoping, agents, verification, tooling, and safety pillars; the
`airx rules` / `airx compare` / `airx init` subcommands; SARIF/Markdown
reporters; waivers; platform sub-scores and parity delta — all shipped in
0.2.0. Still open: HTML report, the GitHub Action, and `airx fix` (see
`plan.md` §12 and `plan-v2-fable.md` §1).

[Unreleased]: https://github.com/YoavLax/AI-Repo-Analyzer/commits/main
