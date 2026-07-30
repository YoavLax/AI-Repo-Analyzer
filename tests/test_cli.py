"""CLI behavior tests (exit codes, subcommands, waivers)."""
import json
from pathlib import Path

from click.testing import CliRunner

from airx.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(*args: str):
    return CliRunner().invoke(main, list(args))


def test_analyze_clean_repo_exits_zero_json():
    result = _run("analyze", str(FIXTURES / "repo_good_skill"), "--format", "json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["score"]["grade"] in ("A", "B")


def test_analyze_error_repo_exits_one_by_default():
    result = _run("analyze", str(FIXTURES / "repo_bad_skill"))
    assert result.exit_code == 1


def test_analyze_fail_on_never_exits_zero():
    result = _run("analyze", str(FIXTURES / "repo_bad_skill"), "--fail-on", "never")
    assert result.exit_code == 0


def test_analyze_min_score_gate():
    result = _run("analyze", str(FIXTURES / "repo_good_skill"), "--min-score", "99.9", "--fail-on", "never")
    assert result.exit_code == 1


def test_analyze_ignore_prefix_removes_findings():
    result = _run("analyze", str(FIXTURES / "repo_bad_skill"), "--format", "json",
                  "--ignore", "skills.", "--fail-on", "never")
    data = json.loads(result.output)
    assert all(not f["rule_id"].startswith("skills.") for f in data["findings"])


def test_analyze_html_writes_report_alongside_primary_output(tmp_path):
    html_path = tmp_path / "report.html"
    result = _run("analyze", str(FIXTURES / "repo_bad_skill"), "--fail-on", "never",
                  "--html", str(html_path))
    assert result.exit_code == 0
    content = html_path.read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")
    assert "<details" in content
    assert f"Report saved to: {html_path}" in result.output


def test_analyze_html_flag_without_path_uses_default_filename():
    with CliRunner().isolated_filesystem():
        result = _run("analyze", str(FIXTURES / "repo_bad_skill"), "--fail-on", "never", "--html")
        assert result.exit_code == 0
        assert Path("airx-report.html").exists()
        assert "Report saved to: airx-report.html" in result.output


def test_analyze_platform_filter_runs():
    result = _run("analyze", str(FIXTURES / "repo_good_skill"), "--platform", "claude", "--fail-on", "never")
    assert result.exit_code == 0


def test_waiver_suppresses_error_and_is_reported(tmp_path: Path):
    # Empty repo: foundation.entrypoint.present is an ERROR; waiving it must
    # remove it from findings and list it under waivers.
    (tmp_path / ".airx.yml").write_text(
        "waivers:\n"
        "  - rule: foundation.entrypoint.present\n"
        "    reason: 'Test waiver.'\n",
        encoding="utf-8",
    )
    result = _run("analyze", str(tmp_path), "--format", "json", "--fail-on", "never")
    data = json.loads(result.output)
    assert all(f["rule_id"] != "foundation.entrypoint.present" for f in data["findings"])
    assert data["waivers"] == [
        {"rule": "foundation.entrypoint.present", "reason": "Test waiver.",
         "expires": None, "approved_by": None}
    ]
    assert data["score"]["has_error_finding"] is False


def test_expired_waiver_with_today_is_not_applied(tmp_path: Path):
    (tmp_path / ".airx.yml").write_text(
        "waivers:\n"
        "  - rule: foundation.entrypoint.present\n"
        "    reason: 'Old waiver.'\n"
        "    expires: '2020-01-01'\n",
        encoding="utf-8",
    )
    result = _run("analyze", str(tmp_path), "--format", "json", "--fail-on", "never",
                  "--today", "2026-01-01")
    data = json.loads(result.output)
    assert any(f["rule_id"] == "foundation.entrypoint.present" for f in data["findings"])
    assert data["expired_waivers"][0]["rule"] == "foundation.entrypoint.present"


def test_malformed_airx_yml_is_usage_error(tmp_path: Path):
    (tmp_path / ".airx.yml").write_text("waivers: [oops\n", encoding="utf-8")
    result = _run("analyze", str(tmp_path))
    assert result.exit_code == 2


def test_rules_json_lists_catalog():
    result = _run("rules", "--format", "json")
    assert result.exit_code == 0
    catalog = json.loads(result.output)
    ids = {r["id"] for r in catalog}
    assert "skills.name.dirname-match" in ids
    assert all({"id", "pillar", "weight", "severity", "platforms", "effort"} <= set(r) for r in catalog)


def test_rules_md_renders_tables():
    result = _run("rules", "--format", "md")
    assert result.exit_code == 0
    assert result.output.startswith("# Rule catalog")
    assert "| ID |" in result.output


def test_compare_detects_regression(tmp_path: Path):
    good = _run("analyze", str(FIXTURES / "repo_good_skill"), "--format", "json", "--fail-on", "never")
    bad = _run("analyze", str(FIXTURES / "repo_bad_skill"), "--format", "json", "--fail-on", "never")
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(good.output, encoding="utf-8")
    new_path.write_text(bad.output, encoding="utf-8")

    regression = _run("compare", str(old_path), str(new_path))
    assert regression.exit_code == 1
    assert "->" in regression.output

    same = _run("compare", str(old_path), str(old_path))
    assert same.exit_code == 0


def test_compare_rejects_non_report(tmp_path: Path):
    bogus = tmp_path / "x.json"
    bogus.write_text("{}", encoding="utf-8")
    result = _run("compare", str(bogus), str(bogus))
    assert result.exit_code == 2


def test_init_scaffolds_and_refuses_overwrite(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        first = runner.invoke(main, ["init"])
        assert first.exit_code == 0
        assert Path(".airx.yml").exists()
        second = runner.invoke(main, ["init"])
        assert second.exit_code == 2
        forced = runner.invoke(main, ["init", "--force"])
        assert forced.exit_code == 0
