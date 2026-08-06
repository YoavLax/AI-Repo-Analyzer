"""Canonical JSON report (schema 0.2.0).

Every v0.1.0 key is preserved verbatim; v0.2.0 only adds keys
(plan-v2-fable.md §3.9). Output is deterministic: all lists sorted, no
wall-clock, no environment reads.
"""
from __future__ import annotations

import json as _json
from pathlib import PurePosixPath

from airx import __version__
from airx.discovery import ArtifactIndex
from airx.remediation import build_plan
from airx.rules.registry import RULESET_VERSION
from airx.scoring import ScoreCard

_TOKEN_CAVEAT = "Token counts are estimates (heuristic tokenizer, ~15% error)."
_EXPIRY_CAVEAT = (
    "Waiver expiry was not evaluated (no --today/AIRX_TODAY date supplied); "
    "expiring waivers remain active."
)


def _rel(index: ArtifactIndex, abs_path) -> PurePosixPath:
    try:
        return PurePosixPath(abs_path.resolve().relative_to(index.root).as_posix())
    except ValueError:
        return PurePosixPath(str(abs_path))


def to_json_dict(index: ArtifactIndex, card: ScoreCard) -> dict:
    findings = []
    for ev in card.evaluations:
        if not ev.applicable or ev.waived:
            continue
        for path, diag in ev.diagnostics:
            findings.append({
                "rule_id": diag.rule_id,
                "pillar": ev.meta.pillar.value,
                "severity": diag.severity.value,
                "source": ev.meta.source.value,
                "weight": ev.meta.weight,
                "path": str(path) if path is not None else None,
                "line": diag.line,
                "message": diag.message,
                "context": diag.context,
                "doc_url": ev.meta.doc_url,
                "why": ev.meta.why or None,
                "fix": ev.meta.fix or None,
                "effort": ev.meta.effort,
            })
    findings.sort(key=lambda f: (f["path"] or "", f["line"] or 0, f["rule_id"]))

    pillars = [
        {
            "id": p.pillar.value,
            "weight": p.weight,
            "score": None if p.score is None else round(p.score, 4),
            "presence_ratio": p.presence_ratio,
            "quality_ratio": p.quality_ratio,
            "rule_count": p.rule_count,
        }
        for p in card.pillars
    ]

    artifacts = [
        {
            "path": str(a.rel_path),
            "kind": a.kind.value,
            "platform": a.platform.value,
            "parse_error": a.parse_error,
        }
        for a in index.artifacts
    ]

    facts = index.facts
    repo_facts = None
    if facts is not None:
        repo_facts = {
            "languages": [[ext, count] for ext, count in facts.languages],
            "package_scripts": list(facts.package_scripts),
            "makefile_targets": list(facts.makefile_targets),
            "test_evidence": facts.test_evidence,
            "lint_evidence": facts.lint_evidence,
            "build_evidence": facts.build_evidence,
            "ci_workflows": [str(p) for p in facts.ci_workflows],
            "has_env_example": facts.has_env_example,
            "has_devcontainer": facts.has_devcontainer,
            "has_setup_script": facts.has_setup_script,
            "version_pins": list(facts.version_pins),
        }

    caveats = [_TOKEN_CAVEAT]
    if card.today is None and any(w.expires for w in card.waived_rules):
        # Fires only when no --today/AIRX_TODAY date was available; with a
        # date, expiry WAS evaluated and expired waivers surface separately.
        caveats.append(_EXPIRY_CAVEAT)

    return {
        "schema_version": "0.2.0",
        "tool_version": __version__,
        "ruleset_version": RULESET_VERSION,
        "profile": card.profile,
        "platform": card.platform,
        "target": {"root": str(index.root)},
        "score": {
            "overall": card.overall,
            "grade": card.grade,
            "raw_grade": card.raw_grade,
            "grade_capped": card.grade_capped,
            "has_error_finding": card.has_error_finding,
            "copilot": card.copilot,
            "claude": card.claude,
            "parity_delta": card.parity_delta,
            "maturity_level": card.maturity_level,
            "maturity_label": card.maturity_label,
        },
        "pillars": pillars,
        "inventory": {
            "skills_found": [str(_rel(index, s.path)) for s in index.skills],
            "skill_parse_errors": [str(p) for p, _ in index.skill_parse_errors],
            "copilot_instructions": str(_rel(index, index.copilot_instructions.path)) if index.copilot_instructions else None,
            "agents_md": [str(p) for p in index.agents_md_paths],
            "claude_md": str(index.claude_md_path) if index.claude_md_path else None,
            "gemini_md": str(index.gemini_md_path) if index.gemini_md_path else None,
            "artifacts": artifacts,
            "repo_facts": repo_facts,
        },
        "findings": findings,
        "waivers": [
            {"rule": w.rule, "reason": w.reason, "expires": w.expires, "approved_by": w.approved_by}
            for w in card.waived_rules
        ],
        "expired_waivers": [
            {"rule": w.rule, "reason": w.reason, "expires": w.expires, "approved_by": w.approved_by}
            for w in card.expired_waivers
        ],
        "ignored_rules": list(card.ignored_rules),
        "remediation_plan": [
            {
                "rank": e.rank,
                "rule_id": e.rule_id,
                "score_gain": e.score_gain,
                "effort": e.effort,
                "action": e.action,
                "paths": list(e.paths),
            }
            for e in build_plan(card)
        ],
        "caveats": caveats,
    }


def to_json(index: ArtifactIndex, card: ScoreCard) -> str:
    return _json.dumps(to_json_dict(index, card), indent=2, sort_keys=False)
