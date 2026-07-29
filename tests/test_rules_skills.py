from pathlib import Path

from airx.parser import parse
from airx.model import Severity
from airx.rules import skills as rules


def _doc(tmp_path: Path, name: str, frontmatter_yaml: str, body: str = "\n# Body\n"):
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    raw = f"---\n{frontmatter_yaml}\n---\n{body}"
    path.write_text(raw, encoding="utf-8")
    return parse(path)


def test_name_dirname_mismatch_is_error(tmp_path):
    doc = _doc(tmp_path, "deploy-helper", "name: deployer\ndescription: Deploys things when asked.")
    sat, diags = rules.check_name_dirname_match(doc)
    assert sat == 0.0
    assert diags[0].severity == Severity.ERROR


def test_name_dirname_match_passes(tmp_path):
    doc = _doc(tmp_path, "deploy-helper", "name: deploy-helper\ndescription: Deploys things when asked.")
    sat, diags = rules.check_name_dirname_match(doc)
    assert sat == 1.0
    assert diags == []


def test_name_type_coercion_detected(tmp_path):
    doc = _doc(tmp_path, "x", "name: true\ndescription: Deploys things when asked.")
    sat, diags = rules.check_name_type(doc)
    assert sat == 0.0
    assert "bool" in diags[0].message


def test_name_charset_rejects_uppercase_and_slash(tmp_path):
    doc = _doc(tmp_path, "x", "name: My/Skill\ndescription: Deploys things when asked.")
    sat, diags = rules.check_name_charset(doc)
    assert sat == 0.0


def test_description_person_voice_flags_first_person(tmp_path):
    doc = _doc(tmp_path, "x", "name: x\ndescription: I can help you deploy things.")
    sat, diags = rules.check_description_person_voice(doc)
    assert sat == 0.0


def test_description_person_voice_passes_third_person(tmp_path):
    doc = _doc(tmp_path, "x", "name: x\ndescription: Deploys packaged releases when asked.")
    sat, diags = rules.check_description_person_voice(doc)
    assert sat == 1.0


def test_description_quality_scores_good_over_bad(tmp_path):
    good = _doc(
        tmp_path, "good",
        "name: good\n"
        "description: >-\n"
        "  Validates and deploys packaged releases to staging. Use this skill\n"
        "  whenever the user asks to deploy, ship, or release a build.\n",
    )
    bad = _doc(tmp_path, "bad", "name: bad\ndescription: Helps with stuff.")
    good_sat, _ = rules.check_description_quality(good)
    bad_sat, _ = rules.check_description_quality(bad)
    assert good_sat > bad_sat


def test_yaml_anchor_detected(tmp_path):
    doc = _doc(tmp_path, "x", "name: &n x\ndescription: *n")
    sat, diags = rules.check_yaml_anchors(doc)
    assert sat == 0.0


def test_references_resolve_flags_broken_and_escaping(tmp_path):
    doc = _doc(
        tmp_path, "refs",
        "name: refs\ndescription: Uses references. Use this skill when the user asks to test references.",
        body="\nSee [missing](scripts/missing.sh) and [outside](../../outside.txt).\n",
    )
    sat, diags = rules.check_references_resolve(doc)
    assert sat == 0.0
    assert len(diags) == 2


def test_references_resolve_not_applicable_when_no_refs(tmp_path):
    doc = _doc(tmp_path, "norefs", "name: norefs\ndescription: Does something. Use this skill when asked to do something.")
    assert rules.check_references_resolve(doc) is None


def test_references_resolve_passes_for_valid_reference(tmp_path):
    skill_dir = tmp_path / "goodrefs"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "helper.py").write_text("print('hi')\n", encoding="utf-8")
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\nname: goodrefs\ndescription: Uses references. Use this skill when asked.\n---\n"
        "\nSee [helper](helper.py) for details.\n",
        encoding="utf-8",
    )
    doc = parse(path)
    sat, diags = rules.check_references_resolve(doc)
    assert sat == 1.0
    assert diags == []


def test_sizing_lines_fails_over_threshold(tmp_path):
    body = "\n" + ("Line of text.\n" * 600)
    doc = _doc(tmp_path, "big", "name: big\ndescription: Does something. Use this skill when asked.", body=body)
    sat, diags = rules.check_sizing_lines(doc)
    assert sat == 0.0


def test_compat_claude_only_is_always_satisfied(tmp_path):
    doc = _doc(tmp_path, "x", "name: x\ndescription: Does something. Use this skill when asked.\nmodel: opus")
    sat, diags = rules.check_compat_claude_only(doc)
    assert sat == 1.0
    assert len(diags) == 1
