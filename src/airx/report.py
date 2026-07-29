"""Terminal and JSON report rendering."""
from __future__ import annotations

import json
from pathlib import PurePosixPath

from airx import __version__
from airx.discovery import ArtifactIndex
from airx.model import Severity
from airx.scoring import ScoreCard


def _rel(index: ArtifactIndex, abs_path) -> PurePosixPath:
    try:
        return PurePosixPath(abs_path.resolve().relative_to(index.root).as_posix())
    except ValueError:
        return PurePosixPath(str(abs_path))


def to_json_dict(index: ArtifactIndex, card: ScoreCard) -> dict:
    findings = []
    for ev in card.evaluations:
        if not ev.applicable:
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

    return {
        "schema_version": "0.1.0",
        "tool_version": __version__,
        "target": {"root": str(index.root)},
        "score": {
            "overall": card.overall,
            "grade": card.grade,
            "raw_grade": card.raw_grade,
            "grade_capped": card.grade_capped,
            "has_error_finding": card.has_error_finding,
        },
        "pillars": pillars,
        "inventory": {
            "skills_found": [str(_rel(index, s.path)) for s in index.skills],
            "skill_parse_errors": [str(p) for p, _ in index.skill_parse_errors],
            "copilot_instructions": str(_rel(index, index.copilot_instructions.path)) if index.copilot_instructions else None,
            "agents_md": [str(p) for p in index.agents_md_paths],
            "claude_md": str(index.claude_md_path) if index.claude_md_path else None,
        },
        "findings": findings,
    }


def to_json(index: ArtifactIndex, card: ScoreCard) -> str:
    return json.dumps(to_json_dict(index, card), indent=2, sort_keys=False)


_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def to_terminal(index: ArtifactIndex, card: ScoreCard) -> str:
    lines: list[str] = []
    lines.append(f"AI Readiness Analyzer — {index.root}")
    lines.append("")
    cap_note = f"  (capped from {card.raw_grade})" if card.grade_capped else ""
    lines.append(f"Overall score: {card.overall:.1f}/100   Grade: {card.grade}{cap_note}")
    lines.append("")
    lines.append("Pillars:")
    for p in card.pillars:
        if p.score is None:
            lines.append(f"  {p.pillar.value:<14} not scored (0 rules registered)")
            continue
        lines.append(
            f"  {p.pillar.value:<14} {p.score*100:5.1f}%   "
            f"(presence {p.presence_ratio*100:5.1f}%, quality {p.quality_ratio*100:5.1f}%, "
            f"weight {p.weight}, {p.rule_count} rules)"
        )
    lines.append("")

    findings = []
    for ev in card.evaluations:
        if not ev.applicable:
            continue
        for path, diag in ev.diagnostics:
            findings.append((path, diag))
    findings.sort(key=lambda t: (_SEVERITY_ORDER[t[1].severity], str(t[0] or ""), t[1].rule_id))

    if findings:
        lines.append(f"Findings ({len(findings)}):")
        for path, diag in findings:
            loc = f"{path}" if path else "(repo)"
            if diag.line:
                loc += f":{diag.line}"
            lines.append(f"  [{diag.severity.value:7}] {diag.rule_id:32} {loc}")
            lines.append(f"            {diag.message}")
    else:
        lines.append("No findings.")

    return "\n".join(lines)
