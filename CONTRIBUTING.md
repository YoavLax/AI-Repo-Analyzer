# Contributing to AI Readiness Analyzer

Thanks for your interest in contributing. This project is early (pre-1.0). The
original design lives in [`plan.md`](plan.md) (read §3, the determinism
contract, first) and the v0.2.0 architecture in
[`plan-v2-fable.md`](plan-v2-fable.md). The generated rule catalog is
[`docs/RULES.md`](docs/RULES.md).

## Development setup

```bash
git clone https://github.com/YoavLax/agent-compass.git
cd agent-compass
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
pytest -v
```

## The one rule that overrides all others: determinism

This project's entire value proposition is that the same commit always
produces the same score. Every contribution must preserve that. Concretely,
rule functions in `src/airx/rules/**` must **never**:

- call `datetime.now()`, `time.time()`, or anything wall-clock-dependent
- use `random` or any other non-seeded randomness
- read environment variables or make network calls
- depend on filesystem iteration order (use the sorted output of `fs.scan`)
- depend on the operating system's path separator, case sensitivity, or locale

If you need genuinely non-deterministic behavior (e.g. actually executing a
repo's build/test commands), it must live in an explicitly opt-in code path
that is excluded from the score — see `plan.md` section 3.2.

## Adding a rule

Rules are pure functions registered with the `@rule(...)` decorator in
`src/airx/rules/registry.py`. There is one module per pillar under
`src/airx/rules/` (`foundation`, `quality`, `scoping`, `skills`, `agents`,
`verification`, `tooling`, `safety`):

- **`RuleScope.SKILL`** rules run once per matching file (e.g. every
  `SKILL.md`) and are averaged across files.
- **`RuleScope.REPO`** rules run once per repository (e.g. "does an entry
  point exist at all"). Repo rules that report on individual files return
  `(rel_path, Diagnostic)` pairs instead of bare `Diagnostic`s.

Every rule returns either:

- `None` — not applicable to this input (excluded from both the numerator and
  denominator of its pillar's presence/quality ratio; see `plan.md` §6.3), or
- `(satisfaction, diagnostics)` — `satisfaction` in `[0.0, 1.0]`
  (`1.0`/`[]` for a clean pass; `0.0` with one or more `Diagnostic`s for a
  binary failure; a continuous value for graded rules).

When adding a rule:

1. Pick the right `pillar`, `applicability` (`PRESENCE` vs `QUALITY` — see
   `plan.md` §6.2), `severity`, and `source` (`SPEC` if it's derived from a
   published specification, `ADVISORY` if it's a best-practice opinion).
2. Fill in the v0.2.0 metadata: `platforms` (which agent stack the rule is
   about — drives the copilot/claude sub-scores), `why` (one sentence on why
   it matters), `fix` (one actionable sentence — it becomes the remediation
   plan's `action`), and `effort` (`mechanical` < `additive` < `authoring` <
   `organizational` — drives remediation ranking).
3. Cite the source of truth in `doc_url` and in a comment — every rule in
   this project traces back to a specific piece of documentation or a
   demonstrable failure mode. "Because it seems like good practice" is not
   sufficient justification on its own.
4. Add unit tests covering the pass case, the fail case, and (if the rule can
   be `None`) the not-applicable case.
5. If the rule changes scores materially, add or update a fixture repo under
   `tests/fixtures/` and the corresponding assertions in
   `tests/test_e2e_fixtures.py`.
6. Advisory heuristic rules must be `warning` or `info` severity, not
   `error` — the registry **enforces** this at import time; `error` is
   reserved for objective, spec-backed failure modes (see `plan.md` §13 and
   `_ADVISORY_ERROR_ALLOWLIST` in `registry.py`).
7. Regenerate the catalog page: `airx rules --format md > docs/RULES.md`
   (CI diffs it).

## Vendored code

The `SKILL.md` validation rules in `src/airx/rules/skills.py` and the
thresholds in `src/airx/config.py` are vendored from
[AgentEval](https://github.com/YoavLax/AgentEval) (MIT licensed) rather than
imported as a dependency — see the docstring at the top of `config.py` for
why. If you're fixing a bug that also exists upstream in AgentEval, please
consider contributing the fix there too.

## Tests

```bash
pytest -v                 # full suite
pytest tests/test_rules_skills.py -v   # a single module
```

The suite includes a determinism check (`tests/test_determinism.py`) that
runs analysis 10× per fixture and asserts byte-identical JSON output. Any
change that breaks this check will not be merged.

## Pull requests

- Keep changes focused; unrelated refactors make review harder.
- Update `plan.md` if you change the scoring model, rule catalog, or resolve
  one of the open questions in §14.
- Add a line to `CHANGELOG.md` under `[Unreleased]`.
- Make sure `pytest -v` passes locally before opening the PR — CI runs the
  same suite across Ubuntu, Windows, and macOS.

## Reporting bugs / requesting features

Open a GitHub issue. For anything security-related, see
[`SECURITY.md`](SECURITY.md) instead of filing a public issue.
