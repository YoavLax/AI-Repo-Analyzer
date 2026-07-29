"""Markdown report (`--format md`) — suitable for PR comments and job summaries.

A pure function of the canonical JSON dict, so it inherits its determinism.
"""
from __future__ import annotations

from airx.discovery import ArtifactIndex
from airx.report.json import to_json_dict
from airx.scoring import ScoreCard

_SEVERITY_EMOJI = {"error": "🔴", "warning": "🟡", "info": "🔵"}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _cell(text: str) -> str:
    """Escape free text for a GFM table cell: literal pipes and newlines break rows."""
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(index: ArtifactIndex, card: ScoreCard) -> str:
    data = to_json_dict(index, card)
    score = data["score"]

    lines: list[str] = []
    lines.append("# AI Readiness Report")
    lines.append("")
    cap = f" (capped from {score['raw_grade']})" if score["grade_capped"] else ""
    lines.append(f"**Overall: {score['overall']:.1f}/100 — Grade {score['grade']}**{cap}")
    lines.append("")
    if score["copilot"] is not None or score["claude"] is not None:
        lines.append("| Platform | Score |")
        lines.append("|---|---|")
        if score["copilot"] is not None:
            lines.append(f"| GitHub Copilot | {score['copilot']:.1f} |")
        if score["claude"] is not None:
            lines.append(f"| Claude Code | {score['claude']:.1f} |")
        if score["parity_delta"] is not None:
            lines.append(f"| Parity delta | {score['parity_delta']:.1f} |")
        lines.append("")

    lines.append("## Pillars")
    lines.append("")
    lines.append("| Pillar | Score | Presence | Quality | Weight | Rules |")
    lines.append("|---|---|---|---|---|---|")
    for p in data["pillars"]:
        if p["score"] is None:
            lines.append(f"| {p['id']} | _not scored_ | — | — | {p['weight']} | {p['rule_count']} |")
        else:
            lines.append(
                f"| {p['id']} | {p['score']*100:.1f}% | {p['presence_ratio']*100:.1f}% "
                f"| {p['quality_ratio']*100:.1f}% | {p['weight']} | {p['rule_count']} |"
            )
    lines.append("")

    findings = sorted(
        data["findings"],
        key=lambda f: (_SEVERITY_ORDER[f["severity"]], f["path"] or "", f["rule_id"]),
    )
    if findings:
        lines.append(f"## Findings ({len(findings)})")
        lines.append("")
        for f in findings:
            emoji = _SEVERITY_EMOJI[f["severity"]]
            loc = f["path"] or "(repo)"
            if f["line"]:
                loc += f":{f['line']}"
            lines.append(f"- {emoji} **`{f['rule_id']}`** — {loc}")
            lines.append(f"  {f['message']}")
            if f["fix"]:
                lines.append(f"  _Fix:_ {f['fix']}")
        lines.append("")

    plan = data["remediation_plan"]
    if plan:
        lines.append("## Top fixes")
        lines.append("")
        lines.append("| # | Gain | Effort | Rule | Action |")
        lines.append("|---|---|---|---|---|")
        for e in plan:
            lines.append(
                f"| {e['rank']} | +{e['score_gain']:.1f} | {e['effort']} "
                f"| `{e['rule_id']}` | {_cell(e['action'])} |"
            )
        lines.append("")

    if data["waivers"]:
        lines.append("## Waivers")
        lines.append("")
        for w in data["waivers"]:
            expiry = f" (expires {w['expires']})" if w["expires"] else ""
            lines.append(f"- `{w['rule']}` — {w['reason']}{expiry}")
        lines.append("")

    for caveat in data["caveats"]:
        lines.append(f"> {caveat}")
    return "\n".join(lines)
