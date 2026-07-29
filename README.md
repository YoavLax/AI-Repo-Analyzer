# AI Readiness Analyzer

**Deterministic AI-readiness scoring for GitHub Copilot and Claude Code repository configuration.**

Point it at a repository. Get back a reproducible score, a letter grade, and a
ranked list of concrete fixes — computed entirely by static analysis, with
zero model calls in the scoring path. Same commit in, byte-identical report
out, every time.

[![CI](https://github.com/YoavLax/AI-Repo-Analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/YoavLax/AI-Repo-Analyzer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

> **Status: pre-1.0, early and evolving.** The full design — 8 scoring
> pillars, ~130 rules, presence/quality weighting, waivers, HTML/SARIF
> reports, a GitHub Action — is documented in [`plan.md`](plan.md). This
> release implements the **Skills** pillar in full and a first cut of the
> **Foundation** pillar. See [Current status](#current-status) below and
> [`CHANGELOG.md`](CHANGELOG.md) for exactly what's built.

---

## Why this exists

Repositories increasingly ship configuration meant for AI coding agents —
`copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md`, `SKILL.md` files, custom
agents, hooks. Whether any of it actually *works* is usually invisible until
an agent silently fails to load a skill, ignores a 900-line instructions
file, or never triggers a skill because its description is too vague.

AI Readiness Analyzer answers "is this repo actually ready for an AI agent?"
the same way a linter answers "does this code compile" — deterministically,
offline, and with a specific file and line number for every issue.

## What it checks today

- **`SKILL.md` files** — the [Agent Skills](https://agentskills.io) open
  standard used by both GitHub Copilot and Claude Code. Frontmatter validity,
  the notorious "name must match the parent directory or VS Code silently
  drops the skill" trap, YAML type-coercion and anchor/alias footguns, a
  0–100 description-quality score (does the description actually trigger
  activation?), progressive-disclosure token budgets, and file-reference
  resolution with path-traversal protection.
- **Entry points** — presence of `.github/copilot-instructions.md`,
  `AGENTS.md`, and `CLAUDE.md`; whether an `AGENTS.md` is actually visible to
  Claude Code (it isn't, unless bridged — a very common miss); length and
  structure heuristics.

See [`plan.md`](plan.md) §7 for the full rule catalog (implemented and
planned) with citations back to the GitHub Copilot and Claude Code
documentation each rule is derived from.

## Quickstart

```bash
git clone https://github.com/YoavLax/AI-Repo-Analyzer.git
cd AI-Repo-Analyzer
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -e .

airx analyze /path/to/some/repo
```

```
AI Readiness Analyzer — /path/to/some/repo

Overall score: 56.2/100   Grade: D

Pillars:
  foundation       31.1%   (presence  77.8%, quality   0.0%, weight 20, 6 rules)
  skills           89.6%   (presence 100.0%, quality  82.7%, weight 15, 30 rules)
  ...

Findings (3):
  [error  ] skills.name.dirname-match   .github/skills/deploy/SKILL.md
            Name 'deployer' does not match parent directory 'deploy'. VS Code/Copilot silently fails to load this skill.
  [warning] foundation.agentsmd.bridged (repo)
            AGENTS.md exists but no CLAUDE.md bridges it. Claude Code reads CLAUDE.md, not AGENTS.md.
```

Machine-readable output for CI:

```bash
airx analyze . --format json -o report.json
airx analyze . --fail-on error   # exit code 1 if any error-severity finding exists (default)
airx analyze . --fail-on never   # always exit 0, useful for advisory-only runs
```

## How it works

```
path → fs.scan (deterministic, symlink-free traversal)
     → discovery.build_index (finds SKILL.md, copilot-instructions.md, AGENTS.md, CLAUDE.md)
     → parser.parse (BOM/CRLF-tolerant YAML-frontmatter + Markdown split)
     → rules/* (pure functions, one per check, registered in a versioned registry)
     → scoring.score (presence/quality aggregation per pillar, grade banding)
     → report.to_json / report.to_terminal
```

Every rule is a pure function of its input. There are no model calls, no
network access, and no wall-clock or environment dependence anywhere in the
scoring path — see [`plan.md`](plan.md) §3 for the full determinism contract
and how it's enforced in tests.

## The scoring model, briefly

Each pillar splits into a **presence** score (does the relevant artifact
exist at all?) and a **quality** score (how good is it?), combined as
`0.4 × presence + 0.6 × quality`. This makes the score resistant to gaming in
both directions: deleting every skill scores *worse* than having one flawed
skill, and duplicating a mediocre skill doesn't inflate the score (it's an
average, not a sum). See [`plan.md`](plan.md) §6 for the full model,
including how rules mark themselves "not applicable" rather than distorting
a ratio they don't belong in.

**Any error-severity finding caps the overall grade at C**, regardless of the
arithmetic score — a repository with a skill that silently fails to load is
not "agent-ready," no matter how good the rest of its configuration looks.
The cap never *upgrades* an already-worse grade; see `airx/scoring.py` and
`tests/test_scoring_grade_cap.py`.

| Score | Grade | Meaning |
|---|---|---|
| 90–100 | A | Agent-native |
| 80–89  | B | Agent-ready |
| 70–79  | C | Agent-capable |
| 55–69  | D | Partially configured |
| 35–54  | E | Minimal |
| 0–34   | F | Not agent-ready |

## Current status

Implemented today (v0.1.0, see [`CHANGELOG.md`](CHANGELOG.md)):

- ✅ Full pipeline: scan → discover → parse → evaluate → score → report
- ✅ **Skills pillar** — 30 rules vendored from
  [AgentEval](https://github.com/YoavLax/AgentEval) (credited, not a runtime
  dependency — see `src/airx/config.py`)
- ✅ **Foundation pillar** — entry-point presence, `AGENTS.md`↔`CLAUDE.md`
  bridge detection, length/structure heuristics
- ✅ Error-severity grade cap, presence/quality anti-gaming model
- ✅ `airx analyze` CLI with terminal and JSON output
- ✅ 33 tests: unit rules, 8 fixture repos, grade-cap proof, byte-for-byte
  determinism checks; verified against real-world repositories

Not yet implemented (see [`plan.md`](plan.md) §12 Roadmap for sequencing):
Quality / Scoping / Agents / Verification / Tooling / Safety pillars, the
`airx rules` / `compare` / `init` / `fix` subcommands, HTML/SARIF/Markdown
reports, waivers, platform sub-scores, and the GitHub Action.

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
