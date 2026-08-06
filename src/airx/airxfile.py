"""`.airx.yml` repository configuration: profile, ignores, waivers (plan.md §6.7).

Waiver expiry is the one place the analyzer would need a clock, so it is
quarantined (plan-v2-fable.md §3.7): expiry is only evaluated against an
explicitly supplied ISO date (`--today` / `AIRX_TODAY`); the scoring path never
reads the wall clock itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

AIRX_FILE_NAME = ".airx.yml"
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AirxConfigError(Exception):
    """Raised when .airx.yml exists but is malformed. CLI maps this to exit 2."""


@dataclass(frozen=True)
class Waiver:
    rule: str
    reason: str
    expires: str | None = None
    approved_by: str | None = None

    def is_expired(self, today: str | None) -> bool:
        """ISO dates compare correctly as strings; without a date we cannot tell."""
        return bool(self.expires and today and self.expires < today)


@dataclass(frozen=True)
class AirxConfig:
    profile: str | None = None
    min_score: float | None = None
    fail_on: str | None = None
    fail_level: int | None = None
    ignore: tuple[str, ...] = ()
    waivers: tuple[Waiver, ...] = ()

    def active_waived_rules(self, today: str | None) -> frozenset[str]:
        return frozenset(w.rule for w in self.waivers if not w.is_expired(today))

    def expired_waivers(self, today: str | None) -> tuple[Waiver, ...]:
        return tuple(w for w in self.waivers if w.is_expired(today))


def _require_str(data: dict, key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AirxConfigError(f"{context}: '{key}' must be a non-empty string")
    return value.strip()


def load(root: Path) -> AirxConfig | None:
    """Load `.airx.yml` from the repo root; None when absent, raises when malformed."""
    path = root / AIRX_FILE_NAME
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise AirxConfigError(f"cannot read {AIRX_FILE_NAME}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AirxConfigError(f"invalid YAML in {AIRX_FILE_NAME}: {exc}") from exc
    if data is None:
        return AirxConfig()
    if not isinstance(data, dict):
        raise AirxConfigError(f"{AIRX_FILE_NAME} must be a YAML mapping")

    profile = data.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise AirxConfigError("'profile' must be a string")

    min_score = data.get("min_score")
    if min_score is not None and not isinstance(min_score, (int, float)):
        raise AirxConfigError("'min_score' must be a number")

    fail_on = data.get("fail_on")
    if fail_on is not None and fail_on not in ("error", "warning", "never"):
        raise AirxConfigError("'fail_on' must be one of: error, warning, never")

    fail_level = data.get("fail_level")
    if fail_level is not None and (not isinstance(fail_level, int) or isinstance(fail_level, bool) or not 1 <= fail_level <= 5):
        raise AirxConfigError("'fail_level' must be an integer from 1 to 5")

    ignore_raw = data.get("ignore", [])
    if not isinstance(ignore_raw, list) or not all(isinstance(i, str) for i in ignore_raw):
        raise AirxConfigError("'ignore' must be a list of rule-id prefixes")

    waivers: list[Waiver] = []
    waivers_raw = data.get("waivers", [])
    if not isinstance(waivers_raw, list):
        raise AirxConfigError("'waivers' must be a list")
    for i, entry in enumerate(waivers_raw):
        context = f"waivers[{i}]"
        if not isinstance(entry, dict):
            raise AirxConfigError(f"{context}: must be a mapping")
        rule = _require_str(entry, "rule", context)
        reason = _require_str(entry, "reason", context)
        expires = entry.get("expires")
        if expires is not None:
            expires = str(expires)
            if not _ISO_DATE_RE.match(expires):
                raise AirxConfigError(f"{context}: 'expires' must be an ISO date (YYYY-MM-DD)")
        approved_by = entry.get("approved_by")
        if approved_by is not None and not isinstance(approved_by, str):
            raise AirxConfigError(f"{context}: 'approved_by' must be a string")
        waivers.append(Waiver(rule=rule, reason=reason, expires=expires, approved_by=approved_by))

    return AirxConfig(
        profile=profile,
        min_score=float(min_score) if min_score is not None else None,
        fail_on=fail_on,
        fail_level=fail_level,
        ignore=tuple(ignore_raw),
        waivers=tuple(waivers),
    )


INIT_TEMPLATE = """\
# AI Readiness Analyzer configuration (https://github.com/YoavLax/agent-compass)
version: 1

# Weight profile: standard | minimal | enterprise
profile: standard

# Fail `airx analyze` when the overall score is below this value (0 disables).
min_score: 0

# Severity gate: error | warning | never
fail_on: error

# Fail `airx analyze` when the maturity level (1-5, derived from the grade)
# is below this value. Unset disables the gate.
# fail_level: 3

# Rule-id prefixes to skip entirely (they leave the score's denominator).
ignore: []
#  - skills.compat.unverified

# Waivers score the rule as satisfied but stay visible in the report.
waivers: []
#  - rule: skills.present
#    reason: "Domain knowledge lives in an internal plugin marketplace."
#    expires: "2027-01-01"
#    approved_by: "platform-team"
"""
