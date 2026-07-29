"""Human-readable terminal report."""
from __future__ import annotations

from airx.discovery import ArtifactIndex
from airx.model import Severity
from airx.remediation import build_plan
from airx.scoring import ScoreCard

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def to_terminal(index: ArtifactIndex, card: ScoreCard) -> str:
    lines: list[str] = []
    lines.append(f"AI Readiness Analyzer — {index.root}")
    lines.append("")
    cap_note = f"  (capped from {card.raw_grade})" if card.grade_capped else ""
    lines.append(f"Overall score: {card.overall:.1f}/100   Grade: {card.grade}{cap_note}")
    if card.copilot is not None or card.claude is not None:
        copilot = f"{card.copilot:.1f}" if card.copilot is not None else "n/a"
        claude = f"{card.claude:.1f}" if card.claude is not None else "n/a"
        parity = f"   parity delta {card.parity_delta:.1f}" if card.parity_delta is not None else ""
        lines.append(f"Platforms:     copilot {copilot}   claude {claude}{parity}")
    if card.profile != "standard":
        lines.append(f"Profile:       {card.profile}")
    lines.append("")
    lines.append("Pillars:")
    for p in card.pillars:
        if p.score is None:
            reason = "0 rules registered" if p.rule_count == 0 else "weight 0 in profile"
            lines.append(f"  {p.pillar.value:<14} not scored ({reason})")
            continue
        lines.append(
            f"  {p.pillar.value:<14} {p.score*100:5.1f}%   "
            f"(presence {p.presence_ratio*100:5.1f}%, quality {p.quality_ratio*100:5.1f}%, "
            f"weight {p.weight}, {p.rule_count} rules)"
        )
    lines.append("")

    findings = []
    for ev in card.evaluations:
        if not ev.applicable or ev.waived:
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

    plan = build_plan(card, limit=5)
    if plan:
        lines.append("")
        lines.append("Top fixes (estimated score gain):")
        for entry in plan:
            lines.append(f"  {entry.rank}. +{entry.score_gain:.1f}  [{entry.effort:<14}] {entry.rule_id}")
            lines.append(f"     {entry.action}")

    if card.waived_rules:
        lines.append("")
        lines.append(f"Waived rules ({len(card.waived_rules)}):")
        for w in card.waived_rules:
            expiry = f", expires {w.expires}" if w.expires else ""
            lines.append(f"  {w.rule} — {w.reason}{expiry}")
    if card.expired_waivers:
        lines.append("")
        lines.append(f"Expired waivers (ignored, {len(card.expired_waivers)}):")
        for w in card.expired_waivers:
            lines.append(f"  {w.rule} — expired {w.expires}")

    return "\n".join(lines)
