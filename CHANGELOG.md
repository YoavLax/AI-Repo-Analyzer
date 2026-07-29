# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) for its
report schema and ruleset (see `plan.md` section 3, determinism guarantee D7).

## [Unreleased]

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

### Not yet implemented
See `plan.md` section 12 (Roadmap) for the full sequencing. Not yet built:
quality, scoping, agents, verification, tooling, and safety pillars; the
`airx rules` / `airx compare` / `airx init` subcommands; HTML/SARIF/Markdown
reporters; waivers; platform sub-scores and parity delta; the GitHub Action.

[Unreleased]: https://github.com/YoavLax/AI-Repo-Analyzer/commits/main
