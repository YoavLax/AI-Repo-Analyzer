---
mode: agent
description: Author a new AgentCompass scoring rule end-to-end (rule function, tests, docs/RULES.md, ruleset version bump).
---

Add a new scoring rule to AgentCompass following
[`CONTRIBUTING.md`](../../CONTRIBUTING.md)'s "Adding a rule" section and the
determinism contract:

1. Ask for (or infer from context) the pillar, the rule id, the spec/failure
   mode it's derived from, and its severity/effort.
2. Add a pure `@rule(...)`-decorated function to the matching
   `src/airx/rules/<pillar>.py` module. Never call `datetime.now()`,
   `time.time()`, unseeded randomness, environment variables, network calls,
   or depend on filesystem iteration order or path separators/case.
3. Extend `model.py`/`patterns.py`/`discovery.py` first if the rule needs a
   new `ArtifactKind` or `ArtifactIndex` field.
4. Add pass/fail/not-applicable unit tests in `tests/test_rules_<pillar>.py`
   using `tmp_path`-built micro-repos.
5. Regenerate `docs/RULES.md` via `airx rules --format md` and bump
   `RULESET_VERSION` in `src/airx/rules/registry.py`.
6. Run `pytest -v` and show the passing output before finishing.
