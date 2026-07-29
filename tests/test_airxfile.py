""".airx.yml loading and waiver-expiry tests."""
from pathlib import Path

import pytest

from airx.airxfile import AirxConfig, AirxConfigError, Waiver, load


def _write(root: Path, content: str) -> None:
    (root / ".airx.yml").write_text(content, encoding="utf-8")


def test_absent_file_returns_none(tmp_path: Path) -> None:
    assert load(tmp_path) is None


def test_full_config_loads(tmp_path: Path) -> None:
    _write(tmp_path, (
        "version: 1\n"
        "profile: enterprise\n"
        "min_score: 70\n"
        "fail_on: warning\n"
        "ignore:\n  - skills.compat\n"
        "waivers:\n"
        "  - rule: skills.present\n"
        "    reason: 'Skills live in an internal marketplace.'\n"
        "    expires: '2027-01-01'\n"
        "    approved_by: platform-team\n"
    ))
    cfg = load(tmp_path)
    assert cfg == AirxConfig(
        profile="enterprise", min_score=70.0, fail_on="warning",
        ignore=("skills.compat",),
        waivers=(Waiver(rule="skills.present", reason="Skills live in an internal marketplace.",
                        expires="2027-01-01", approved_by="platform-team"),),
    )


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    _write(tmp_path, "waivers: [unterminated\n")
    with pytest.raises(AirxConfigError):
        load(tmp_path)


def test_waiver_without_reason_raises(tmp_path: Path) -> None:
    _write(tmp_path, "waivers:\n  - rule: skills.present\n")
    with pytest.raises(AirxConfigError):
        load(tmp_path)


def test_bad_expires_format_raises(tmp_path: Path) -> None:
    _write(tmp_path, "waivers:\n  - rule: r\n    reason: x\n    expires: 'soon'\n")
    with pytest.raises(AirxConfigError):
        load(tmp_path)


def test_bad_fail_on_raises(tmp_path: Path) -> None:
    _write(tmp_path, "fail_on: sometimes\n")
    with pytest.raises(AirxConfigError):
        load(tmp_path)


def test_expiry_only_evaluated_with_a_date() -> None:
    waiver = Waiver(rule="r", reason="x", expires="2026-01-01")
    assert waiver.is_expired(today=None) is False
    assert waiver.is_expired(today="2025-12-31") is False
    assert waiver.is_expired(today="2026-01-02") is True

    cfg = AirxConfig(waivers=(waiver,))
    assert cfg.active_waived_rules(today=None) == {"r"}
    assert cfg.active_waived_rules(today="2026-06-01") == frozenset()
    assert cfg.expired_waivers(today="2026-06-01") == (waiver,)
