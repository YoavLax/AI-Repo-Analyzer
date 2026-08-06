"""Per-rule recall floor: which rules does the test suite ever drive to FAIL?

A rule that no test has ever made fail is a rule whose detection is unproven.
It may be correct, dead, or unreachable — from the suite alone there is no way
to tell, and a refactor that silently breaks it goes green.

Grepping for rule ids answers a weaker question ("is it mentioned?"). This
wraps every registered rule function and records what it actually returned
across the whole suite, so the answer is observed rather than inferred.

    python tools/recall_floor.py            # human table
    python tools/recall_floor.py --json     # machine-readable, for CI

Exit code is 0 always; this reports a number, it does not gate. Gating comes
later, once the number has a baseline worth defending.
"""
from __future__ import annotations

import functools
import json
import sys
from collections import defaultdict
from pathlib import Path

# `tests/test_server.py` imports `tests.test_ingest`, which needs the
# repository root importable. A plain `pytest` run inserts it via rootdir;
# invoking pytest.main() from a script does not.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

import airx.rules  # noqa: F401  (registers every rule)
from airx.rules import registry

#: rule id -> {"fail", "pass", "na"} seen anywhere (unit call or full scan).
OUTCOMES: dict[str, set[str]] = defaultdict(set)
#: rule id -> same, but only for calls that went through the scoring engine.
#: The gap between the two is the interesting part: a rule can be proven at the
#: unit level and still be unreachable end-to-end, because discovery never
#: surfaces the artifact or applicability gates it out first.
ENGINE_OUTCOMES: dict[str, set[str]] = defaultdict(set)


def _classify(result) -> str:
    """A rule returns None (not applicable), or (satisfaction, diagnostics)."""
    if result is None:
        return "na"
    try:
        satisfaction, _ = result
    except (TypeError, ValueError):  # pragma: no cover - malformed rule result
        return "pass"
    return "pass" if satisfaction >= 1.0 else "fail"


def _instrument() -> None:
    """Wrap every rule function on both routes it can be called by.

    Unit tests call `rules.check_name_charset(doc)` — a module attribute,
    resolved at call time, so patching the module catches those. The scoring
    engine calls `meta.fn` out of the registry, so the registry entry is
    rebuilt too (`RuleMeta` is frozen, hence `replace` rather than assignment).

    A single rule therefore gets two wrappers, and the engine wrapper delegates
    to the module one; `ENGINE_OUTCOMES` records only the outer call, so the
    two routes stay distinguishable.
    """
    import dataclasses
    import importlib

    for rule_id, meta in list(registry._REGISTRY.items()):
        module = importlib.import_module(meta.fn.__module__)
        name = meta.fn.__name__
        original = getattr(module, name, meta.fn)

        @functools.wraps(original)
        def unit_recorder(*args, __fn=original, __id=rule_id, **kwargs):
            result = __fn(*args, **kwargs)
            OUTCOMES[__id].add(_classify(result))
            return result

        setattr(module, name, unit_recorder)

        @functools.wraps(unit_recorder)
        def engine_recorder(*args, __fn=unit_recorder, __id=rule_id, **kwargs):
            result = __fn(*args, **kwargs)
            ENGINE_OUTCOMES[__id].add(_classify(result))
            return result

        registry._REGISTRY[rule_id] = dataclasses.replace(meta, fn=engine_recorder)


def main() -> int:
    as_json = "--json" in sys.argv
    _instrument()

    code = pytest.main(["-q", "--no-header", "-p", "no:cacheprovider", "tests"])
    if code != 0:
        print(f"\ntest suite failed (exit {code}); recall numbers are not meaningful",
              file=sys.stderr)
        return 0

    rules = registry.all_rules()
    detected = {r.id for r in rules if "fail" in OUTCOMES.get(r.id, set())}
    reachable = {r.id for r in rules if "fail" in ENGINE_OUTCOMES.get(r.id, set())}

    never_ran = [r for r in rules if not OUTCOMES.get(r.id)]
    unit_only = [r for r in rules if r.id in detected and r.id not in reachable]
    undetected = [r for r in rules if OUTCOMES.get(r.id) and r.id not in detected]

    if as_json:
        print(json.dumps({
            "total": len(rules),
            "detection_proven": len(detected),
            "engine_reachable": len(reachable),
            "unit_only": sorted(r.id for r in unit_only),
            "never_failed": sorted(r.id for r in undetected),
            "never_invoked": sorted(r.id for r in never_ran),
        }, indent=2))
        return 0

    by_pillar: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in rules:
        by_pillar[r.pillar.value][2] += 1
        if r.id in detected:
            by_pillar[r.pillar.value][0] += 1
        if r.id in reachable:
            by_pillar[r.pillar.value][1] += 1

    total = len(rules)
    print(f"\n{'=' * 78}")
    print("RECALL FLOOR")
    print(f"  detection proven   {len(detected):>3}/{total}  "
          f"({100 * len(detected) / total:.0f}%)  something made the rule fail")
    print(f"  engine reachable   {len(reachable):>3}/{total}  "
          f"({100 * len(reachable) / total:.0f}%)  ...through a full scan, not a direct call")
    print("=" * 78)
    print(f"\n{'pillar':<14}{'detected':>10}{'reachable':>12}")
    for pillar in sorted(by_pillar):
        det, reach, tot = by_pillar[pillar]
        print(f"{pillar:<14}{det:>5}/{tot:<4}{reach:>8}/{tot:<4} "
              f"{'#' * int(20 * reach / tot) if tot else ''}")

    groups = (
        ("NEVER INVOKED — nothing in the suite reaches this rule", never_ran),
        ("NEVER FAILED — only ever observed passing, so detection is unproven", undetected),
        ("UNIT ONLY — the check works in isolation but no full scan has ever "
         "surfaced it; a discovery or applicability change could kill it silently", unit_only),
    )
    for title, group in groups:
        if not group:
            continue
        print(f"\n{title} ({len(group)}):")
        for r in sorted(group, key=lambda r: (r.severity.value, r.pillar.value, r.id)):
            print(f"  [{r.severity.value:7}] w{r.weight:<3} {r.id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
