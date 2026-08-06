# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) for its
report schema and ruleset (see `plan.md` section 3, determinism guarantee D7).

## [Unreleased] — 0.3.0 — "AgentCompass"

AgentCompass — your compass for AI-agent-ready repos: a web UI over the analyzer.
Paste a public GitHub URL, get the full report, no clone. Design and rationale
in [`plan-v3-codecompass.md`](plan-v3-codecompass.md). The scoring pipeline,
report schema, and determinism contract are untouched — ingest happens before
the pipeline, exactly like the CLI's clone path.

### Added
- **Streaming progress** — `POST /api/analyze/stream` returns NDJSON: a
  `{"type":"progress","phase","done","total"}` line as each phase advances, then
  a terminal `result` or `error` line. The counts come from the ingest itself
  (files listed, files fetched), so the web UI's progress bar tracks the actual
  run instead of easing on a timer. `POST /api/analyze` is unchanged, and the
  report on the result line is byte-identical to it — the progress hook is a
  side channel that cannot influence the snapshot (D1).
- **10 new rules** (catalog now 104) from a 2026-08 best-practice research
  pass over `shanraisshan/claude-code-best-practice`, humanlayer.dev's
  "Writing a good CLAUDE.md", SFEIR Institute's Claude Code best practices,
  GitHub Copilot's cloud-agent docs, and agentskills.io:
  - *foundation*: `foundation.entrypoint.conditional-references` (progressive
    disclosure applied to entry-point references); GEMINI.md is now recognized
    as an additional Copilot-visible entry point (`foundation.entrypoint.present`,
    `foundation.copilot.entrypoint`) and participates in every entry-point
    quality check.
  - *quality*: `quality.entrypoint.no-lint-rules` ("Claude is not an expensive
    linter" — flags code-style micro-rules that duplicate a linter config),
    `quality.references.pointers-not-snippets` (referenced companion docs
    shouldn't embed large, stale-prone code blocks).
  - *agents*: `agents.commands.present` and `agents.commands.frontmatter.valid`
    (`.claude/commands/**/*.md`, a new discovered artifact kind), and
    `agents.mcp-servers.resolve` (an agent's `mcp-servers`/`mcpServers`
    frontmatter values must name a server actually declared in the repo's MCP
    config).
  - *safety*: `safety.permissions.least-privilege` (flags unrestricted Bash
    grants — bare `Bash`, `Bash(*)`, or `"*"` — in committed
    `.claude/settings.json` `permissions.allow`).
  - *tooling*: `tooling.mcp.not-overloaded` (soft ceiling on declared MCP
    servers) and `tooling.copilot-setup-steps.present` (a new discovered
    artifact kind, `.github/workflows/copilot-setup-steps.yml`, that
    pre-installs dependencies for Copilot's cloud-agent environment).
  - *verification*: `verify.hooks.enforces-lint` (at least one hook should
    run the formatter/linter mechanically instead of leaving style review to
    the agent).
- **Schema currency fixes** found by the same research pass, reducing false
  positives in existing rules: `KNOWN_FRONTMATTER_FIELDS` (SKILL.md/command
  schema) gained `when_to_use`, `disallowed-tools`, `paths`, `effort`,
  `background`, `shell`, `arguments`; `KNOWN_AGENT_FIELDS` gained the current
  16-field Claude subagent schema (`disallowedTools`, `permissionMode`,
  `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`, `background`,
  `effort`, `isolation`, `initialPrompt`); `KNOWN_CLAUDE_SETTINGS_KEYS` grew
  from ~20 to ~90 keys to match the now-documented `.claude/settings.json`
  surface (`safety.settings.valid`).
- Ruleset version bumped to `0.3.0` (report `schema_version` is unchanged;
  see `plan.md` §3, determinism guarantee D7).
- **AgentCompass web UI** (`web/`): React 18 + TypeScript + Vite + Tailwind
  single-page app — URL input hero, score ring with grade, Copilot/Claude
  platform bars with parity delta, pillar table, findings with severity
  filters, top-fixes cards, waivers panel, light/dark theme.
- **Clone-free GitHub ingest** (`src/airx/ingest.py`, stdlib-only): one
  GitHub Trees API call lists the full tree, then only the files the rules
  actually read are fetched from `raw.githubusercontent.com` — classified
  artifacts, the four probe files, and skill directories. The snapshot is
  pinned to a single resolved commit SHA; caps enforced (≤ 400 fetched files,
  ≤ 2 MB/file, ≤ 20 MB total); symlink blobs and unsafe paths are dropped;
  truncated trees, 404s, and rate limits map to clear `IngestError`s. Only
  `api.github.com` and `raw.githubusercontent.com` are ever contacted, with
  an injectable fetcher so tests never touch the network.
- **`airx_server` FastAPI app** (`src/airx_server/`): `POST /api/analyze`
  (GitHub source, or a confined local path when `ALLOW_LOCAL_PATHS=true`)
  returning the canonical report plus a `meta` block; `GET /api/health`;
  `GET /api/version`; SPA static serving from `STATIC_DIR` with an
  `index.html` fallback; `{"error": {"code", "message"}}` problem bodies;
  a concurrency gate (`MAX_CONCURRENT_ANALYSES`, default 4). FastAPI is
  imported lazily so the base library install stays dependency-free.
- **Containers & deployment**: multi-stage `Dockerfile` (Node builds
  `web/dist`, Python slim runtime, non-root user, healthcheck on
  `/api/health`), `docker-compose.yml` with a commented private-repos
  local-path block, and a Helm chart (`deploy/helm/agentcompass`) with
  probes, security context, optional ingress/HPA, and a `localRepos` mode.
- **New extras** in `pyproject.toml`: `web = [fastapi, uvicorn]`; the `dev`
  extra grows fastapi + uvicorn + httpx (for Starlette's TestClient).
- **CI additions**: a `web` job (Node 20 typecheck + build), a `docker` job
  (image build + container smoke test against `/api/health`), and a `helm`
  job (`helm lint` + `helm template`), alongside the unchanged Python matrix.
- **Tests**: `tests/test_ingest.py` (URL parsing, selection logic, caps,
  error mapping, and an end-to-end proof that a clone-free snapshot scores
  identically to the same tree analyzed from disk) and
  `tests/test_server.py` (API contract, error statuses, local-path
  confinement incl. traversal/symlink escapes, SPA fallback) — all against
  a fake fetcher, no network.
- `--html [FILE]` on `airx analyze`: writes a self-contained, collapsible HTML
  report (`report/html.py`) alongside the primary output — no CDN assets, no
  JavaScript (native `<details>/<summary>`), all repo-sourced text escaped.
  Defaults to `airx-report.html` when no path is given.
- Remote analysis for the CLI: `airx analyze owner/repo` or a clone URL,
  shallow-cloned to a temp directory and removed afterwards.
- Artifact fetching runs concurrently (8 workers): an analysis is latency-bound
  on dozens of independent round trips, so this cuts a 59-file scan from ~27 s
  to ~2.4 s. The snapshot is unchanged — files land at their own paths and the
  listing is sorted independently, so completion order is unobservable.

### Fixed (found by the pre-release adversarial review)
- **SSRF containment now holds across redirects.** The host allowlist was
  applied only to the initial URL, so a 3xx from GitHub could send the request
  — and the `GITHUB_TOKEN` header, which CPython forwards across hosts and
  even across an https→http downgrade — to an arbitrary host. Redirects are
  re-validated per hop and the token is stripped off `api.github.com`.
- **Response reads are capped at read time** (2 MB per file, 64 MB per API
  response) instead of after the whole body was buffered.
- **`/api/analyze` no longer starves the server.** A blocking semaphore in a
  sync endpoint parked Starlette's shared threadpool, so concurrent analyses
  made `/api/health` hang (and Kubernetes liveness kill the pod). The endpoint
  is async, the gate is an `asyncio.Semaphore` keyed per event loop, and the
  CPU-bound pipeline runs in an executor.
- **Web scores match CLI scores.** Ingest now prunes the same vendored
  directories `fs.scan` excludes (committed `node_modules/`, `dist/`, …), and
  the analyzed repository's own `.airx.yml` (profile, ignores, waivers) is
  fetched and applied; a malformed one returns 422 instead of being ignored.
- Read-phase network failures map to 502 with a message instead of an opaque
  500; `airx_server.app.app` is a cached singleton; request-validation errors
  use the documented `{"error": {...}}` shape; `/tree/` URLs with a trailing
  slash no longer produce a bogus ref; `.dockerignore` excludes `**/*.egg-info`
  so build metadata stays out of the image.

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

[Unreleased]: https://github.com/YoavLax/agent-compass/commits/main
