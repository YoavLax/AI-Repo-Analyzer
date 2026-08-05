# Copilot instructions — AI Readiness Analyzer

## Overview

AI Readiness Analyzer (AgentCompass) is a deterministic, offline static
analyzer that scores how ready a repository is for AI coding agents (GitHub
Copilot / Claude Code). Point it at a repo and it returns a reproducible
score, a letter grade, and a ranked list of concrete fixes — same commit in,
byte-identical report out, every time. See [`README.md`](../README.md) and
[`plan.md`](../plan.md) for the full design.

## Tech stack

- **Backend/CLI**: Python 3.11+, `click`, `PyYAML`. Package lives under
  `src/airx/` (rule engine, scoring, report formats) and `src/airx_server/`
  (FastAPI web API).
- **Frontend**: `web/` — React 18 + Vite + TypeScript + Tailwind.
- **Packaging**: setuptools (`pyproject.toml`, `[build-system]`).
- **Container**: multi-stage `Dockerfile` (Vite build of `web/` +
  FastAPI/uvicorn runtime), orchestrated with `docker-compose.yml`.

## Coding guidelines

- **Determinism is the one rule that overrides all others**, because the
  same commit must always produce the same score. Rule functions in
  `src/airx/rules/**` must never call `datetime.now()`/`time.time()`, use
  unseeded randomness, read environment variables, make network calls, or
  depend on filesystem iteration order or OS path separators/case. See
  [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full contract.
- Every rule traces back to a specific spec or documented failure mode —
  cite it in `doc_url` and a comment, since "seems like good practice"
  alone is not sufficient justification for a rule.
- Add unit tests for every new rule (pass / fail / not-applicable cases) in
  `tests/test_rules_<pillar>.py` so that regressions are caught
  automatically, and regenerate `docs/RULES.md` after adding or changing a
  rule.

## Project structure

```
src/airx/            CLI, discovery, scoring, rule engine
  rules/              one module per pillar (foundation, quality, scoping,
                       skills, agents, verification, tooling, safety)
  report/             terminal / JSON / Markdown / SARIF report writers
src/airx_server/      FastAPI web API used by web/
web/                  React + Vite frontend (CodeCompass UI)
tests/                pytest suite; tests/fixtures/ holds synthetic repos
                      used for end-to-end scoring assertions
docs/RULES.md         generated rule catalog (regenerate, don't hand-edit)
```

## Resources

- **Run the full backend test suite**: `pytest -v` (or `python -m pytest -q`
  for a quieter run) to ensure changes don't regress the rule engine.
  Config: `[tool.pytest.ini_options]` in `pyproject.toml`; fixtures in
  `conftest.py`.
- **Typecheck + build the frontend**: `cd web && npm run build` (runs
  `tsc --noEmit && vite build` — the schema-drift/typecheck gate) to avoid
  shipping a broken build; run this after any `web/src` change.
- **Build a distributable Python package**: `python -m build`.
- **Regenerate the rule catalog**: `airx rules --format md`.
- **Verify against a live repo**: `docker compose up -d --build`, then
  `POST /api/analyze` (see `README.md` Quickstart), or `airx analyze <path>`
  against a local clone.
- After making a change, run the tests and iterate until they pass; when you
  claim a fix works, show the output of the test run as evidence.
