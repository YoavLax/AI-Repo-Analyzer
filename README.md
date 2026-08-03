# AI Readiness Analyzer

**Deterministic AI-readiness scoring for GitHub Copilot and Claude Code repository configuration.**

Point it at a repository. Get back a reproducible score, a letter grade, and a
ranked list of concrete fixes — computed entirely by static analysis, with
zero model calls in the scoring path. Same commit in, byte-identical report
out, every time.

[![CI](https://github.com/YoavLax/AI-Repo-Analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/YoavLax/AI-Repo-Analyzer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

> **Status: v0.3.0 "AgentCompass" — pre-1.0.** All eight scoring pillars are
> live with a catalog of 104 rules, platform sub-scores, waivers,
> terminal/JSON/Markdown/SARIF reports, and a clone-free web UI. The original
> design document is [`plan.md`](plan.md); the v0.2.0 refactor plan is
> [`plan-v2-fable.md`](plan-v2-fable.md) and the web-app plan is
> [`plan-v3-codecompass.md`](plan-v3-codecompass.md); the full generated rule
> catalog is [`docs/RULES.md`](docs/RULES.md). See
> [`CHANGELOG.md`](CHANGELOG.md) for exactly what's built.

---

## Why this exists

Repositories increasingly ship configuration meant for AI coding agents —
`copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md`, `SKILL.md` files, custom
agents, path-scoped instructions, hooks, MCP servers. Whether any of it
actually *works* is usually invisible until an agent silently fails to load a
skill, ignores a 900-line instructions file, or never triggers a skill because
its description is too vague.

AI Readiness Analyzer answers "is this repo actually ready for an AI agent?"
the same way a linter answers "does this code compile" — deterministically,
offline, and with a specific file and line number for every issue.

## What it checks

Eight pillars, 104 rules ([full catalog](docs/RULES.md)):

| Pillar | Weight | What it covers |
|---|---|---|
| Foundation | 20 | Entry points exist and parse; `AGENTS.md`↔`CLAUDE.md` bridge; length and structure; section coverage; `@import` resolution |
| Instruction quality | 15 | Specific, justified, exemplified directives; no boilerplate, stale markers, or credential-shaped strings; commands and links resolve |
| Context scoping | 12 | Path-scoped `*.instructions.md`; the missing-`applyTo` silent no-op; dead globs; monolith detection |
| Skills | 15 | The full [Agent Skills](https://agentskills.io) validation set: frontmatter, the dirname-match silent-drop trap, description quality (0–100), token budgets, CWE-59 reference escapes, progressive disclosure |
| Agents & prompts | 10 | Custom-agent frontmatter, description quality, least-privilege `tools`, prompt→agent reference resolution |
| Verification | 12 | Documented **and resolvable** test/build/lint commands; CI; iterate-until-green and show-evidence instructions; hooks schema |
| Tooling | 8 | MCP config validity and secret indirection; setup scripts; devcontainer; version pins |
| Safety | 8 | Committed personal files; permission-bypass settings; secrets in settings/MCP; `curl \| sh` injection surface |

## Quickstart

```bash
git clone https://github.com/YoavLax/AI-Repo-Analyzer.git
cd AI-Repo-Analyzer
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -e .

airx analyze /path/to/some/repo
```

PATH can also be a remote repository — a GitHub `owner/repo` shorthand or any
git clone URL (`https://`, `ssh://`, `git@host:...`). It's shallow-cloned to a
temp directory for the analysis and removed afterwards; requires `git` on PATH.

```bash
airx analyze YoavLax/AI-Repo-Analyzer
airx analyze https://github.com/YoavLax/AI-Repo-Analyzer.git --ref main
```

```
AI Readiness Analyzer — /path/to/some/repo

Overall score: 61.1/100   Grade: D
Platforms:     copilot 62.5   claude 61.1   parity delta 1.4

Pillars:
  foundation      86.4%   (presence 100.0%, quality  77.3%, weight 20, 9 rules)
  skills          99.8%   (presence 100.0%, quality  99.6%, weight 15, 37 rules)
  ...

Findings (20):
  [error  ] skills.name.dirname-match   .github/skills/deploy/SKILL.md
            Name 'deployer' does not match parent directory 'deploy'. VS Code/Copilot silently fails to load this skill.

Top fixes (estimated score gain):
  1. +4.8  [additive      ] verify.test-command.documented
     Document the repository's test command in an entry point so agents can verify their work.
```

### CI usage

```bash
airx analyze . --format json -o report.json     # canonical machine output
airx analyze . --format sarif -o airx.sarif     # GitHub code scanning
airx analyze . --format md                      # PR comment / job summary
airx analyze . --min-score 70 --fail-on error   # quality gate
airx compare baseline.json report.json          # exit 1 on regression
```

Exit codes: `0` passed · `1` gate failed · `2` input/config error · `3` internal error.

### Configuration (`.airx.yml`)

`airx init` scaffolds it:

```yaml
profile: standard        # or: minimal, enterprise (weight profiles)
min_score: 70
fail_on: error
ignore:
  - skills.compat.unverified
waivers:
  - rule: skills.present
    reason: "Domain knowledge lives in an internal plugin marketplace."
    expires: "2027-01-01"
    approved_by: platform-team
```

Waived rules score as satisfied but stay visible in the report. Waiver expiry
is only evaluated against an explicit date (`--today 2026-07-29` or
`AIRX_TODAY`) — the scoring path never reads the clock, so output stays
reproducible.

## AgentCompass — the web UI

**AgentCompass** — your compass for AI-agent-ready repos. Paste a public GitHub
repository URL into the browser, get the full report: overall score and grade,
Copilot/Claude platform bars, per-pillar breakdown, filterable findings, and
the ranked top fixes.

A **Copilot / Claude Code / All** toggle scopes the report to one agent
harness, so a Claude Code-only (or Copilot-only) team isn't scored against
rules for a harness they don't use. The selection carries over on re-analysis
and is reflected in the shareable URL (`?platform=claude`).

The scan is **clone-free**: one GitHub Trees API call lists every file in the
repository, and only the files the rules actually read — classified AI
artifacts, the four probe files, skill directories — are fetched (kilobytes,
not the repo). Name-only rules see the complete listing, content rules see
real files, and the whole snapshot is pinned to a single commit SHA. Nothing
is persisted; each request is self-contained.

### Run it

```bash
docker compose up          # then open http://localhost:8080
```

Or without Docker:

```bash
pip install -e ".[dev]"                     # server deps (or ".[web]" for runtime only)
cd web && npm install && npm run build      # → web/dist
cd .. && STATIC_DIR=web/dist uvicorn airx_server.app:app --port 8080
```

### Server configuration

All configuration is environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | unset | Token for the online scan's GitHub API calls (raises the rate limit from 60 to 5,000 req/h); sent only to `api.github.com` |
| `ALLOW_LOCAL_PATHS` | `false` | Enable analyzing repositories mounted on the server (local-path mode) |
| `LOCAL_REPOS_ROOT` | unset | Root directory local-path analyses are strictly confined to |
| `STATIC_DIR` | unset | Directory of the built SPA (`web/dist`) to serve |
| `MAX_CONCURRENT_ANALYSES` | `4` | Cap on simultaneous analyses |
| `MAX_FETCH_FILES` | `400` | Online-scan cap on classified AI-artifact files fetched per repository; raise it to analyze larger repos without local-path mode |
| `MAX_FILE_BYTES` | `2097152` (2 MB) | Online-scan per-file size cap, in bytes |
| `MAX_TOTAL_BYTES` | `20971520` (20 MB) | Online-scan total fetch-size cap, in bytes |

### API

- `POST /api/analyze` with `{"source": "<github url or owner/repo>", "ref": null}`
  — or `{"path": "<relative path>"}` in local-path mode — returns the canonical
  JSON report plus a `meta` block (`source`, `ref`, `resolved_sha`,
  `listed_files`, `fetched_files`, `duration_ms`). Errors come back as
  `{"error": {"code", "message"}}` with `400`/`404`/`413`/`422`/`429`.
  An optional `"platform": "copilot"|"claude"|"all"` field scopes scoring to
  one platform's rules (default `"all"`), mirroring the CLI's `--platform`
  flag; the applied value is echoed back as the report's top-level `platform` key.
- `GET /api/health` — liveness. `GET /api/version` — `{version, local_mode}`.

### Private repositories

The online scan only reaches public GitHub. For private code, self-host
AgentCompass next to your repositories: mount them read-only into the
container, set `ALLOW_LOCAL_PATHS=true` and `LOCAL_REPOS_ROOT`, and analyze by
relative path — the analysis itself never touches the network. A Helm chart
for Kubernetes deployments lives at `deploy/helm/agentcompass`; see
[`deploy/README.md`](deploy/README.md) for both setups.

## How it works

```
path → fs.scan            deterministic, symlink-free traversal
     → discovery          declarative artifact patterns (skills, agents, prompts,
                          instructions, hooks, MCP, settings — see src/airx/patterns.py)
     → probe              repo facts: test/build/lint evidence, CI, hygiene
     → rules/*            94 pure functions, one per check, in a versioned registry
     → scoring            presence/quality split per pillar, platform sub-scores,
                          profiles, waivers, grade banding
     → report/*           terminal | json | markdown | sarif + ranked remediation plan
```

Every rule is a pure function of its input. There are no model calls, no
network access, and no wall-clock or environment dependence anywhere in the
scoring path — see [`plan.md`](plan.md) §3 for the determinism contract and
`tests/test_determinism.py` for its enforcement.

## The scoring model, briefly

Each pillar splits into a **presence** score (does the relevant artifact
exist at all?) and a **quality** score (how good is it?), combined as
`0.4 × presence + 0.6 × quality`. This makes the score resistant to gaming in
both directions: deleting every skill scores *worse* than having one flawed
skill, and duplicating a mediocre skill doesn't inflate the score (it's an
average, not a sum). Rules that don't apply are removed from both numerator
and denominator; a pillar with nothing applicable at all is excluded from the
weighted overall rather than scoring a vacuous 100%.

**Any error-severity finding caps the overall grade at C**, regardless of the
arithmetic score — and error severity is reserved for objective,
spec-verifiable failures (a skill that silently fails to load, a committed
credential), never for style heuristics. The cap never *upgrades* an
already-worse grade.

| Score | Grade | Meaning |
|---|---|---|
| 90–100 | A | Agent-native |
| 80–89  | B | Agent-ready |
| 70–79  | C | Agent-capable |
| 55–69  | D | Partially configured |
| 35–54  | E | Minimal |
| 0–34   | F | Not agent-ready |

Every rule is tagged by platform, so the report also carries separate
`copilot` and `claude` scores and their **parity delta** — a rich `AGENTS.md`
with no `CLAUDE.md` bridge shows up as a Copilot/Claude gap, not just a
buried warning.

## Commands

```
airx analyze PATH [--format terminal|json|md|sarif] [-o FILE]
                  [--html [FILE]]
                  [--profile minimal|standard|enterprise]
                  [--platform copilot|claude|all]
                  [--min-score N] [--fail-on error|warning|never]
                  [--ignore PREFIX]... [--no-waivers] [--today YYYY-MM-DD]
                  [--ref BRANCH|TAG|COMMIT]         # remote PATH only
airx rules        [--format terminal|json|md]     # the catalog; generates docs/RULES.md
airx compare      OLD.json NEW.json               # regression diff for CI
airx init         [--force]                       # scaffold .airx.yml
```

`PATH` is a local directory, a GitHub `owner/repo` shorthand, or any git clone
URL — remote repos are shallow-cloned to a temp directory and cleaned up
after analysis.

`--html [FILE]` additionally writes a self-contained, offline HTML report
with collapsible sections (pillars, findings by severity, top fixes, waivers,
inventory) — default path `airx-report.html` when no `FILE` is given.

## Not yet implemented

The composite GitHub Action, `airx fix`, duplication detection,
and nested-monorepo aggregation — see [`plan.md`](plan.md) §12 and
[`plan-v2-fable.md`](plan-v2-fable.md) §1 for sequencing.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) — in particular, the section on the
determinism contract, which every rule must preserve.

## Security

See [`SECURITY.md`](SECURITY.md) for the threat model and how to report a
vulnerability.

## Credits

The `SKILL.md` validation rules and their thresholds are vendored from
[AgentEval](https://github.com/YoavLax/AgentEval) (MIT licensed). The rule
catalog is derived from the published
[Agent Skills specification](https://agentskills.io), the
[Claude Code documentation](https://code.claude.com/docs/en/best-practices),
and [GitHub Copilot's custom-instructions guidance](https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/)
— see [`plan.md`](plan.md) §15 for the full bibliography.

## License

[MIT](LICENSE) © 2026 Yoav Lax
