"""SARIF 2.1.0 report (`--format sarif`) for GitHub code scanning."""
from __future__ import annotations

import json as _json

from airx import __version__
from airx.discovery import ArtifactIndex
from airx.rules.registry import all_rules
from airx.scoring import ScoreCard

_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


def to_sarif(index: ArtifactIndex, card: ScoreCard) -> str:
    driver_rules = [
        {
            "id": meta.id,
            "shortDescription": {"text": meta.summary},
            "helpUri": meta.doc_url,
            "properties": {
                "pillar": meta.pillar.value,
                "source": meta.source.value,
                "weight": meta.weight,
            },
        }
        for meta in all_rules()
    ]
    rule_index = {r["id"]: i for i, r in enumerate(driver_rules)}

    results = []
    for ev in card.evaluations:
        if not ev.applicable or ev.waived:
            continue
        for path, diag in ev.diagnostics:
            location = {
                "physicalLocation": {
                    "artifactLocation": {"uri": str(path) if path is not None else "."},
                    "region": {"startLine": diag.line or 1},
                }
            }
            results.append({
                "ruleId": diag.rule_id,
                "ruleIndex": rule_index.get(diag.rule_id, -1),
                "level": _LEVEL[diag.severity.value],
                "message": {"text": diag.message},
                "locations": [location],
            })
    results.sort(key=lambda r: (r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
                                r["locations"][0]["physicalLocation"]["region"]["startLine"],
                                r["ruleId"]))

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "airx",
                        "version": __version__,
                        "informationUri": "https://github.com/YoavLax/AI-Repo-Analyzer",
                        "rules": driver_rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return _json.dumps(sarif, indent=2, sort_keys=False)
