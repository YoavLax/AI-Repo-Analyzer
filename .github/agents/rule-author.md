---
name: rule-author
description: >-
  Authors new AgentCompass scoring rules end-to-end: registers a `@rule`
  in the right `src/airx/rules/<pillar>.py` module, adds pass/fail/N-A unit
  tests in `tests/test_rules_<pillar>.py`, and regenerates `docs/RULES.md`.
  Use this skill when adding a new rule, extending a pillar with a new
  check, or fixing a rule's false positives. Trigger when the user asks to
  "add a rule", "score X", or "detect Y" in this repository.
tools: ["search", "editFiles", "runCommands"]
---

# Rule author

Adds a new AgentCompass scoring rule from a documented spec or failure mode,
following the determinism contract in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

## Steps

1. Pick the pillar (`foundation`, `quality`, `scoping`, `skills`, `agents`,
   `verification`, `tooling`, `safety`) and confirm the rule traces back to a
   specific spec or a demonstrable failure mode — cite it in `doc_url`.
2. Add a pure `@rule(...)`-decorated function to `src/airx/rules/<pillar>.py`
   returning `None` (not applicable) or `(satisfaction, diagnostics)`. Never
   call `datetime.now()`/`time.time()`, use unseeded randomness, read
   environment variables, make network calls, or depend on filesystem
   iteration order or OS path separators/case.
3. If the rule needs a new artifact type, extend `model.py` (`ArtifactKind`),
   `patterns.py`, and `discovery.py` (`ArtifactIndex` field) first.
4. Add unit tests in `tests/test_rules_<pillar>.py` covering the satisfied,
   violated, and (if applicable) not-applicable cases using `tmp_path`-built
   micro-repos.
5. Regenerate `docs/RULES.md` via `airx rules --format md` (use
   `click.testing.CliRunner` in a Python one-liner and write with
   `encoding="utf-8"` — piping through PowerShell `Set-Content` mangles the
   em dash).
6. Bump `RULESET_VERSION` in `src/airx/rules/registry.py`.
7. Run `pytest -v` and show the passing output as evidence before
   considering the task done.
