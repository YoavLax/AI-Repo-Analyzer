"""Self-contained HTML report (`--html [FILE]`).

A pure function of the canonical JSON dict, so it inherits its determinism.
No external assets (no CDN fonts/JS/CSS) — everything is inlined so the file
opens and works fully offline. Sections use native `<details>/<summary>` so
the report is collapsible without any JavaScript.
"""
from __future__ import annotations

from html import escape

from airx.discovery import ArtifactIndex
from airx.report.json import to_json_dict
from airx.scoring import ScoreCard

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_LABEL = {"error": "Error", "warning": "Warning", "info": "Info"}
_SEVERITY_COLOR = {"error": "#c92a2a", "warning": "#9a7d0a", "info": "#1c6fd6"}
_GRADE_COLOR = {"A": "#1a7f37", "B": "#4c9a2a", "C": "#9a8b00", "D": "#c9622a", "F": "#c92a2a"}


def _e(value) -> str:
    """HTML-escape arbitrary report content (repo-sourced text is untrusted)."""
    return escape(str(value)) if value is not None else ""


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color}">{_e(text)}</span>'


def _section(title: str, body: str, *, open_: bool = False, count: int | None = None) -> str:
    suffix = f" ({count})" if count is not None else ""
    return (
        f'<details class="section"{" open" if open_ else ""}>'
        f"<summary>{_e(title)}{_e(suffix)}</summary>"
        f'<div class="section-body">{body}</div>'
        f"</details>"
    )


def _render_header(data: dict) -> str:
    score = data["score"]
    grade_color = _GRADE_COLOR.get(score["grade"], "#666")
    cap_note = (
        f'<span class="muted"> (capped from {_e(score["raw_grade"])})</span>'
        if score["grade_capped"] else ""
    )
    platform_row = ""
    if score["copilot"] is not None or score["claude"] is not None:
        cells = []
        if score["copilot"] is not None:
            cells.append(f'<div class="stat"><span class="stat-label">Copilot</span><span class="stat-value">{score["copilot"]:.1f}</span></div>')
        if score["claude"] is not None:
            cells.append(f'<div class="stat"><span class="stat-label">Claude</span><span class="stat-value">{score["claude"]:.1f}</span></div>')
        if score["parity_delta"] is not None:
            cells.append(f'<div class="stat"><span class="stat-label">Parity delta</span><span class="stat-value">{score["parity_delta"]:.1f}</span></div>')
        platform_row = f'<div class="stat-row">{"".join(cells)}</div>'

    return f"""
<header>
  <h1>AI Readiness Report</h1>
  <p class="target">{_e(data["target"]["root"])}</p>
  <div class="headline">
    <div class="grade-badge" style="background:{grade_color}">{_e(score["grade"])}</div>
    <div class="overall">
      <span class="overall-value">{score["overall"]:.1f}</span><span class="overall-max">/100</span>
      {cap_note}
      <div class="muted">profile: {_e(data["profile"])} · ruleset {_e(data["ruleset_version"])} · tool {_e(data["tool_version"])}</div>
    </div>
  </div>
  {platform_row}
</header>
"""


def _render_pillars(data: dict) -> str:
    rows = []
    for p in data["pillars"]:
        if p["score"] is None:
            rows.append(
                f'<tr><td>{_e(p["id"])}</td><td colspan="3" class="muted">not scored</td>'
                f'<td>{_e(p["weight"])}</td><td>{_e(p["rule_count"])}</td></tr>'
            )
        else:
            rows.append(
                f"<tr><td>{_e(p['id'])}</td><td>{_pct(p['score'])}</td>"
                f"<td>{_pct(p['presence_ratio'])}</td><td>{_pct(p['quality_ratio'])}</td>"
                f"<td>{_e(p['weight'])}</td><td>{_e(p['rule_count'])}</td></tr>"
            )
    table = (
        "<table><thead><tr><th>Pillar</th><th>Score</th><th>Presence</th>"
        "<th>Quality</th><th>Weight</th><th>Rules</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return _section("Pillars", table)


def _render_finding(f: dict) -> str:
    loc = f["path"] or "(repo)"
    if f["line"]:
        loc += f":{f['line']}"
    extra = []
    if f["why"]:
        extra.append(f'<div class="why"><strong>Why:</strong> {_e(f["why"])}</div>')
    if f["fix"]:
        extra.append(f'<div class="fix"><strong>Fix:</strong> {_e(f["fix"])}</div>')
    if f["doc_url"]:
        extra.append(f'<div class="doc"><a href="{_e(f["doc_url"])}" rel="noopener noreferrer">docs</a></div>')
    return f"""
<div class="finding">
  <div class="finding-head">
    {_badge(_SEVERITY_LABEL[f["severity"]], _SEVERITY_COLOR[f["severity"]])}
    <code class="rule-id">{_e(f["rule_id"])}</code>
    <span class="loc">{_e(loc)}</span>
  </div>
  <div class="message">{_e(f["message"])}</div>
  {"".join(extra)}
</div>
"""


def _render_findings(data: dict) -> str:
    findings = sorted(
        data["findings"],
        key=lambda f: (_SEVERITY_ORDER[f["severity"]], f["path"] or "", f["rule_id"]),
    )
    if not findings:
        return _section("Findings", '<p class="muted">No findings.</p>', count=0)

    by_severity: dict[str, list[dict]] = {}
    for f in findings:
        by_severity.setdefault(f["severity"], []).append(f)

    groups = []
    for sev in ("error", "warning", "info"):
        items = by_severity.get(sev)
        if not items:
            continue
        body = "".join(_render_finding(f) for f in items)
        groups.append(_section(_SEVERITY_LABEL[sev], body, count=len(items)))

    return _section("Findings", "".join(groups), count=len(findings))


def _render_remediation(data: dict) -> str:
    plan = data["remediation_plan"]
    if not plan:
        return ""
    rows = []
    for e in plan:
        paths = ", ".join(e["paths"]) if e["paths"] else "—"
        rows.append(
            f"<tr><td>{e['rank']}</td><td>+{e['score_gain']:.1f}</td><td>{_e(e['effort'])}</td>"
            f"<td><code>{_e(e['rule_id'])}</code></td><td>{_e(e['action'])}</td><td>{_e(paths)}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>#</th><th>Gain</th><th>Effort</th><th>Rule</th>"
        "<th>Action</th><th>Paths</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return _section("Top fixes", table, count=len(plan))


def _render_waivers(data: dict) -> str:
    parts = []
    if data["waivers"]:
        entries = []
        for w in data["waivers"]:
            expiry = f" (expires {_e(w['expires'])})" if w["expires"] else ""
            entries.append(f'<li><code>{_e(w["rule"])}</code> — {_e(w["reason"])}{expiry}</li>')
        items = "".join(entries)
        parts.append(_section("Waivers", f"<ul>{items}</ul>", count=len(data["waivers"])))
    if data["expired_waivers"]:
        items = "".join(
            f'<li><code>{_e(w["rule"])}</code> — expired {_e(w["expires"])}</li>'
            for w in data["expired_waivers"]
        )
        parts.append(_section("Expired waivers (ignored)", f"<ul>{items}</ul>", count=len(data["expired_waivers"])))
    return "".join(parts)


def _render_inventory(data: dict) -> str:
    inv = data["inventory"]
    rows = "".join(
        f"<tr><td>{_e(a['path'])}</td><td>{_e(a['kind'])}</td><td>{_e(a['platform'])}</td>"
        f"<td>{_e(a['parse_error']) if a['parse_error'] else '—'}</td></tr>"
        for a in inv["artifacts"]
    )
    artifacts_table = (
        "<table><thead><tr><th>Path</th><th>Kind</th><th>Platform</th><th>Parse error</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>" if inv["artifacts"] else '<p class="muted">No artifacts discovered.</p>'
    )

    facts_html = '<p class="muted">No repo facts collected.</p>'
    facts = inv.get("repo_facts")
    if facts:
        langs = ", ".join(f"{ext} ({count})" for ext, count in facts["languages"]) or "—"
        facts_html = f"""
<ul class="facts">
  <li><strong>Languages:</strong> {_e(langs)}</li>
  <li><strong>Package scripts:</strong> {_e(", ".join(facts["package_scripts"]) or "—")}</li>
  <li><strong>Makefile targets:</strong> {_e(", ".join(facts["makefile_targets"]) or "—")}</li>
  <li><strong>Test evidence:</strong> {_e(facts["test_evidence"])}</li>
  <li><strong>Lint evidence:</strong> {_e(facts["lint_evidence"])}</li>
  <li><strong>Build evidence:</strong> {_e(facts["build_evidence"])}</li>
  <li><strong>CI workflows:</strong> {_e(", ".join(facts["ci_workflows"]) or "—")}</li>
  <li><strong>.env.example present:</strong> {_e(facts["has_env_example"])}</li>
  <li><strong>Devcontainer present:</strong> {_e(facts["has_devcontainer"])}</li>
  <li><strong>Setup script present:</strong> {_e(facts["has_setup_script"])}</li>
  <li><strong>Version pins:</strong> {_e(", ".join(facts["version_pins"]) or "—")}</li>
</ul>
"""

    body = f"<h3>Artifacts</h3>{artifacts_table}<h3>Repo facts</h3>{facts_html}"
    return _section("Inventory", body)


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  max-width: 980px; margin: 2rem auto; padding: 0 1rem 3rem; line-height: 1.5;
  color: #1b1f23; background: #fff;
}
@media (prefers-color-scheme: dark) {
  body { color: #e6edf3; background: #0d1117; }
  table, .finding, .section { border-color: #30363d !important; }
  th { background: #161b22 !important; }
  .stat, .grade-badge, .badge { color: #fff; }
}
h1 { margin-bottom: 0.15rem; font-size: 1.6rem; }
h3 { margin: 1rem 0 0.4rem; font-size: 1rem; }
.target { color: #666; margin-top: 0; font-size: 0.9rem; word-break: break-all; }
.muted { color: #6a737d; }
header { margin-bottom: 1.5rem; }
.headline { display: flex; align-items: center; gap: 1rem; margin: 0.75rem 0; }
.grade-badge {
  font-size: 2rem; font-weight: 700; color: #fff; border-radius: 0.5rem;
  width: 3.2rem; height: 3.2rem; display: flex; align-items: center; justify-content: center;
}
.overall-value { font-size: 2rem; font-weight: 700; }
.overall-max { color: #6a737d; }
.stat-row { display: flex; gap: 1.5rem; margin-top: 0.5rem; }
.stat { display: flex; flex-direction: column; }
.stat-label { font-size: 0.75rem; color: #6a737d; text-transform: uppercase; }
.stat-value { font-size: 1.1rem; font-weight: 600; }
details.section {
  border: 1px solid #d0d7de; border-radius: 6px; margin-bottom: 0.75rem; overflow: hidden;
}
details.section > summary {
  cursor: pointer; padding: 0.6rem 0.9rem; font-weight: 600; list-style: none;
  background: #f6f8fa;
}
@media (prefers-color-scheme: dark) { details.section > summary { background: #161b22; } }
details.section > summary::-webkit-details-marker { display: none; }
details.section > summary::before { content: "▸ "; }
details.section[open] > summary::before { content: "▾ "; }
.section-body { padding: 0.75rem 0.9rem; }
details.section details.section { margin: 0.5rem 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { border: 1px solid #d0d7de; padding: 0.35rem 0.6rem; text-align: left; }
th { background: #f6f8fa; }
code { background: rgba(110,118,129,0.15); padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.85em; }
.badge { color: #fff; border-radius: 4px; padding: 0.1rem 0.5rem; font-size: 0.78rem; font-weight: 600; margin-right: 0.5rem; }
.finding { border-bottom: 1px solid #eaecef; padding: 0.5rem 0; }
.finding:last-child { border-bottom: none; }
.finding-head { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.loc { color: #6a737d; font-size: 0.85rem; }
.message { margin-top: 0.25rem; }
.why, .fix { font-size: 0.85rem; color: #6a737d; margin-top: 0.15rem; }
.doc a { font-size: 0.85rem; }
ul.facts { margin: 0; padding-left: 1.2rem; }
footer { margin-top: 2rem; font-size: 0.85rem; color: #6a737d; }
"""


def to_html(index: ArtifactIndex, card: ScoreCard) -> str:
    data = to_json_dict(index, card)

    body = "".join([
        _render_header(data),
        _render_pillars(data),
        _render_findings(data),
        _render_remediation(data),
        _render_waivers(data),
        _render_inventory(data),
    ])

    caveats = "".join(f"<p>{_e(c)}</p>" for c in data["caveats"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Readiness Report — {_e(data["target"]["root"])}</title>
<style>{_CSS}</style>
</head>
<body>
{body}
<footer>{caveats}</footer>
</body>
</html>
"""
