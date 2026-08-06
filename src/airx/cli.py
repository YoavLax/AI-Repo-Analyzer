"""Command-line entry point.

Exit codes (plan.md §8.4): 0 passed · 1 gate failed (severity, --min-score, or
--fail-level) · 2 input/config error · 3 unexpected internal error.
"""
from __future__ import annotations

import json as _json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import click

import airx.rules  # noqa: F401  (registers built-in rules on import)
from airx import airxfile, fs
from airx.discovery import build_index
from airx.model import Platform, Severity
from airx.report import to_html, to_json, to_markdown, to_sarif, to_terminal
from airx.rules.registry import RULESET_VERSION, all_rules
from airx.scoring import score

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Matches explicit git clone URLs: https://, http://, ssh://, or the
# scp-like git@host:owner/repo(.git) form.
_GIT_URL_RE = re.compile(r"^(https?://|ssh://|git@)")
# Matches a bare "owner/repo" GitHub shorthand (no scheme, no local path
# separators beyond the single slash).
_GITHUB_SHORTHAND_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _resolve_repo_url(path_arg: str) -> str | None:
    """Return a clonable git URL if PATH_ARG names a remote repo, else None.

    Accepts explicit git URLs (https://, ssh://, git@host:owner/repo) as-is,
    and expands a bare "owner/repo" shorthand to a GitHub HTTPS URL — but
    only when no local directory of that name already exists, so real
    relative paths are never misinterpreted as remote repos.
    """
    if _GIT_URL_RE.match(path_arg):
        return path_arg
    if _GITHUB_SHORTHAND_RE.match(path_arg) and not Path(path_arg).exists():
        return f"https://github.com/{path_arg}.git"
    return None


def _rmtree_force(path: Path) -> None:
    """Remove PATH even if it contains read-only files.

    Git marks files under .git/objects read-only, including on Windows,
    where plain shutil.rmtree(..., ignore_errors=True) silently fails to
    delete them and leaves the temp clone behind.
    """
    def _on_error(func, target, exc_info):  # noqa: ANN001 - shutil callback signature
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=_on_error)


def _clone_repo(url: str, ref: str | None) -> Path:
    """Shallow-clone URL into a fresh temp directory and return its path."""
    if shutil.which("git") is None:
        raise click.UsageError("git is required to analyze a remote repository but was not found on PATH.")
    clone_dir = Path(tempfile.mkdtemp(prefix="airx-clone-"))
    cmd = ["git", "clone", "--depth", "1", "--quiet"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [url, str(clone_dir)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        _rmtree_force(clone_dir)
        stderr = (exc.stderr or "").strip()
        raise click.UsageError(f"failed to clone {url}: {stderr or exc}") from exc
    return clone_dir


@click.group()
@click.version_option(package_name="ai-repo-analyzer")
def main() -> None:
    """AI Readiness Analyzer — deterministic AI-readiness scoring."""


@main.command()
@click.argument("path_arg", metavar="PATH")
@click.option("--format", "fmt", type=click.Choice(["terminal", "json", "md", "sarif"]), default="terminal")
@click.option("--fail-on", type=click.Choice(["error", "warning", "never"]), default=None,
              help="Severity gate (default: error, or the .airx.yml value).")
@click.option("--min-score", type=float, default=None,
              help="Exit 1 when the overall score is below N (default: 0, or the .airx.yml value).")
@click.option("--fail-level", type=click.IntRange(1, 5), default=None,
              help="Exit 1 when the maturity level (1-5, derived from the grade) is below N "
                   "(default: no gate, or the .airx.yml value).")
@click.option("--profile", type=click.Choice(["minimal", "standard", "enterprise"]), default=None,
              help="Weight profile (default: standard, or the .airx.yml value).")
@click.option("--platform", "platform_name", type=click.Choice(["copilot", "claude", "all"]), default="all",
              help="Restrict scoring to rules relevant to one platform.")
@click.option("--ignore", "ignore_prefixes", multiple=True,
              help="Rule-id prefix to skip entirely (repeatable).")
@click.option("--no-waivers", is_flag=True, help="Ignore .airx.yml waivers.")
@click.option("--today", default=None,
              help="ISO date (YYYY-MM-DD) used to evaluate waiver expiry; defaults to "
                   "$AIRX_TODAY, else expiry is not evaluated (keeps output deterministic).")
@click.option("--max-files", type=int, default=fs.DEFAULT_MAX_FILES, help="Traversal cap.")
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("--html", "html_output", type=click.Path(path_type=Path), is_flag=False,
              flag_value="airx-report.html", default=None,
              help="Also write a self-contained, collapsible HTML report "
                   "(default path: airx-report.html when no path is given).")
@click.option("--ref", default=None,
              help="Branch, tag, or commit to check out when PATH is a remote repository.")
def analyze(
    path_arg: str,
    fmt: str,
    fail_on: str | None,
    min_score: float | None,
    fail_level: int | None,
    profile: str | None,
    platform_name: str,
    ignore_prefixes: tuple[str, ...],
    no_waivers: bool,
    today: str | None,
    max_files: int,
    output: Path | None,
    html_output: Path | None,
    ref: str | None,
) -> None:
    """Analyze PATH and print an AI-readiness report.

    PATH is a local directory, a git clone URL (https://, ssh://, git@host:...),
    or a GitHub "owner/repo" shorthand. Remote repos are shallow-cloned to a
    temporary directory for the duration of the analysis and removed afterwards.
    """
    if today is None:
        today = os.environ.get("AIRX_TODAY") or None
    if today is not None and not _ISO_DATE_RE.match(today):
        raise click.UsageError("--today must be an ISO date (YYYY-MM-DD)")

    repo_url = _resolve_repo_url(path_arg)
    if ref is not None and repo_url is None:
        raise click.UsageError("--ref only applies when PATH is a remote repository.")

    clone_dir: Path | None = None
    if repo_url is not None:
        clone_dir = _clone_repo(repo_url, ref)
        path = clone_dir
    else:
        path = Path(path_arg)
        if not path.is_dir():
            raise click.UsageError(f"Path '{path_arg}' does not exist or is not a directory.")

    try:
        try:
            airx_config = airxfile.load(path)
        except airxfile.AirxConfigError as exc:
            raise click.UsageError(str(exc)) from exc

        # Precedence: CLI flag > .airx.yml > built-in default.
        cfg = airx_config or airxfile.AirxConfig()
        effective_profile = profile or cfg.profile or "standard"
        effective_fail_on = fail_on or cfg.fail_on or "error"
        effective_min_score = min_score if min_score is not None else (cfg.min_score or 0.0)
        effective_fail_level = fail_level if fail_level is not None else cfg.fail_level
        if effective_profile not in ("minimal", "standard", "enterprise"):
            raise click.UsageError(f"unknown profile in .airx.yml: {effective_profile!r}")

        platform = None
        if platform_name == "copilot":
            platform = Platform.COPILOT
        elif platform_name == "claude":
            platform = Platform.CLAUDE

        tree = fs.scan(path, max_files=max_files)
        index = build_index(tree)
        card = score(
            index,
            profile=effective_profile,
            airx=airx_config,
            today=today,
            extra_ignore=tuple(ignore_prefixes),
            no_waivers=no_waivers,
            platform=platform,
        )

        renderers = {"terminal": to_terminal, "json": to_json, "md": to_markdown, "sarif": to_sarif}
        rendered = renderers[fmt](index, card)

        if output is not None:
            output.write_text(rendered + "\n", encoding="utf-8")
            click.echo(f"Report saved to: {output}")
        else:
            click.echo(rendered)

        if html_output is not None:
            html_output.write_text(to_html(index, card), encoding="utf-8")
            click.echo(f"Report saved to: {html_output}")

        exit_code = _gate_exit_code(card, effective_fail_on, effective_min_score, effective_fail_level)
    finally:
        if clone_dir is not None:
            _rmtree_force(clone_dir)

    sys.exit(exit_code)


def _gate_exit_code(card, fail_on: str, min_score: float, fail_level: int | None = None) -> int:
    if card.overall < min_score:
        return 1
    if fail_level is not None and card.maturity_level < fail_level:
        return 1
    if fail_on == "never":
        return 0
    if fail_on == "error":
        return 1 if card.has_error_finding else 0
    # fail_on == "warning": any unsatisfied, unwaived rule at warning or error.
    tripped = any(
        ev.applicable and not ev.waived and ev.satisfaction < 1.0
        and ev.meta.severity in (Severity.ERROR, Severity.WARNING)
        for ev in card.evaluations
    )
    return 1 if tripped else 0


@main.command()
@click.option("--format", "fmt", type=click.Choice(["terminal", "json", "md"]), default="terminal")
def rules(fmt: str) -> None:
    """Print the rule catalog."""
    catalog = all_rules()
    if fmt == "json":
        click.echo(_json.dumps([
            {
                "id": m.id, "pillar": m.pillar.value, "scope": m.scope.value,
                "applicability": m.applicability.value, "weight": m.weight,
                "severity": m.severity.value, "source": m.source.value,
                "platforms": [p.value for p in m.platforms], "effort": m.effort,
                "summary": m.summary, "why": m.why or None, "fix": m.fix or None,
                "doc_url": m.doc_url,
            }
            for m in catalog
        ], indent=2))
        return

    if fmt == "md":
        lines = [
            "# Rule catalog",
            "",
            f"Ruleset version `{RULESET_VERSION}` — {len(catalog)} rules. "
            "Generated by `airx rules --format md`; do not edit by hand.",
        ]
        by_pillar: dict[str, list] = {}
        for m in catalog:
            by_pillar.setdefault(m.pillar.value, []).append(m)
        for pillar in sorted(by_pillar):
            lines.append("")
            lines.append(f"## {pillar}")
            lines.append("")
            lines.append("| ID | Kind | Weight | Severity | Source | Platforms | Check |")
            lines.append("|---|---|---|---|---|---|---|")
            for m in by_pillar[pillar]:
                platforms = ", ".join(p.value for p in m.platforms)
                lines.append(
                    f"| `{m.id}` | {m.applicability.value} | {m.weight} | {m.severity.value} "
                    f"| {m.source.value} | {platforms} | {m.summary} |"
                )
        click.echo("\n".join(lines))
        return

    click.echo(f"Rule catalog — ruleset {RULESET_VERSION}, {len(catalog)} rules")
    click.echo("")
    for m in catalog:
        click.echo(f"  [{m.severity.value:7}] {m.id:38} w{m.weight:<3} {m.pillar.value:<12} {m.summary}")


@main.command()
@click.argument("old_report", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("new_report", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def compare(old_report: Path, new_report: Path) -> None:
    """Diff two JSON reports; exit 1 on regression (score drop or new errors)."""
    try:
        old = _json.loads(old_report.read_text(encoding="utf-8-sig"))
        new = _json.loads(new_report.read_text(encoding="utf-8-sig"))
        old_overall = float(old["score"]["overall"])
        new_overall = float(new["score"]["overall"])
        old_grade = old["score"]["grade"]
        new_grade = new["score"]["grade"]
        old_findings = {(f["rule_id"], f.get("path")) for f in old["findings"]}
        new_findings = {(f["rule_id"], f.get("path")) for f in new["findings"]}
        new_errors = sorted(
            (f["rule_id"], f.get("path") or "(repo)")
            for f in new["findings"]
            if f["severity"] == "error" and (f["rule_id"], f.get("path")) not in old_findings
        )
    except (KeyError, TypeError, ValueError, _json.JSONDecodeError) as exc:
        raise click.UsageError(f"not a valid airx JSON report: {exc}") from exc

    delta = new_overall - old_overall
    click.echo(f"Overall: {old_overall:.2f} -> {new_overall:.2f} ({delta:+.2f})")
    click.echo(f"Grade:   {old_grade} -> {new_grade}")

    resolved = sorted(
        f"{rid} @ {path or '(repo)'}" for rid, path in old_findings - new_findings
    )
    introduced = sorted(
        f"{rid} @ {path or '(repo)'}" for rid, path in new_findings - old_findings
    )
    if resolved:
        click.echo(f"Resolved findings ({len(resolved)}):")
        for item in resolved:
            click.echo(f"  - {item}")
    if introduced:
        click.echo(f"New findings ({len(introduced)}):")
        for item in introduced:
            click.echo(f"  + {item}")
    if not resolved and not introduced:
        click.echo("Findings: unchanged")

    regression = delta < -0.005 or bool(new_errors)
    if new_errors:
        click.echo("New error-severity findings:")
        for rid, path in new_errors:
            click.echo(f"  ! {rid} @ {path}")
    sys.exit(1 if regression else 0)


@main.command()
@click.option("--force", is_flag=True, help="Overwrite an existing .airx.yml.")
def init(force: bool) -> None:
    """Scaffold a .airx.yml in the current directory."""
    target = Path.cwd() / airxfile.AIRX_FILE_NAME
    if target.exists() and not force:
        raise click.UsageError(f"{airxfile.AIRX_FILE_NAME} already exists (use --force to overwrite)")
    target.write_text(airxfile.INIT_TEMPLATE, encoding="utf-8")
    click.echo(f"Wrote {target}")


def _run() -> None:  # pragma: no cover - thin wrapper
    try:
        main(standalone_mode=False)
    except click.UsageError as exc:
        click.echo(f"error: {exc.format_message()}", err=True)
        sys.exit(2)
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)
    except click.Abort:
        sys.exit(2)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberate top-level catch (exit code 3)
        click.echo(f"internal error: {exc}", err=True)
        sys.exit(3)


if __name__ == "__main__":
    _run()
