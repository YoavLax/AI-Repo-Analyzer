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


def test_description_person_voice_ignores_when_you_trigger_clause(tmp_path):
    doc = _doc(
        tmp_path, "x",
        "name: x\ndescription: Use when you need to fix a failing test before committing.",
    )
    sat, diags = rules.check_description_person_voice(doc)
    assert sat == 1.0
    assert diags == []


def test_description_person_voice_flags_second_person_outside_trigger_clause(tmp_path):
    doc = _doc(tmp_path, "x", "name: x\ndescription: You can generate reports and validate data.")
    sat, diags = rules.check_description_person_voice(doc)
    assert sat == 0.0
    assert diags[0].severity == Severity.ERROR


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


def test_no_xml_ignores_bare_placeholder_tokens(tmp_path):
    """'<slug>', '<commit>' etc. are a common CLI/doc convention for 'insert
    the real value here' (also covers non-markup uses of angle brackets,
    like a C# generic type parameter '<T>') \u2014 not literal markup that
    would leak into a routing prompt."""
    doc = _doc(
        tmp_path, "x",
        "name: x\ndescription: 'Creates a new errors/<slug>.mdx page and measures the impact of <commit>.'",
    )
    sat, diags = rules.check_description_no_xml(doc)
    assert sat == 1.0
    assert diags == []


def test_no_xml_still_flags_real_markup(tmp_path):
    """A tag with an attribute (real JSX/HTML, e.g. `<Link prefetch={true}>`)
    or a matching closing tag is still flagged."""
    doc = _doc(
        tmp_path, "x",
        "name: x\ndescription: 'Audits <Link prefetch={true}> calls and rewrites <b>bold</b> text.'",
    )
    sat, diags = rules.check_description_no_xml(doc)
    assert sat == 0.0
    assert "<Link prefetch={true}>" in diags[0].message
    assert "<b>" in diags[0].message


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


def test_references_resolve_accepts_a_directory_link(tmp_path):
    """A markdown link to a folder (e.g. `[templates/](templates/)`) is a
    normal way to point at a directory for browsing, not a broken file
    reference \u2014 it resolves as long as the directory is scan-visible and
    non-empty."""
    skill_dir = tmp_path / "dirrefs"
    (skill_dir / "templates").mkdir(parents=True, exist_ok=True)
    (skill_dir / "templates" / "reply-fix.md").write_text("Fixed.\n", encoding="utf-8")
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\nname: dirrefs\ndescription: Uses references. Use this skill when asked.\n---\n"
        "\nSee the templates under [templates/](templates/) for reply phrasing.\n",
        encoding="utf-8",
    )
    doc = parse(path)
    sat, diags = rules.check_references_resolve(doc)
    assert sat == 1.0
    assert diags == []


def test_references_resolve_rejects_an_empty_directory_link(tmp_path):
    skill_dir = tmp_path / "emptydirrefs"
    (skill_dir / "templates").mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\nname: emptydirrefs\ndescription: Uses references. Use this skill when asked.\n---\n"
        "\nSee [templates/](templates/).\n",
        encoding="utf-8",
    )
    doc = parse(path)
    sat, diags = rules.check_references_resolve(doc)
    assert sat == 0.0
    assert len(diags) == 1


def test_references_resolve_skips_example_syntax_in_code_blocks(tmp_path):
    """Illustrative example markdown inside a fenced code block (e.g. a
    template for a *generated* file) is not a live reference the agent needs
    to load, so it must not be flagged as a broken link."""
    doc = _doc(
        tmp_path, "codeblockrefs",
        "name: codeblockrefs\ndescription: Uses references. Use this skill when asked.",
        body=(
            "\nExample structure:\n"
            "\n```txt\n"
            "- [Main README](README.md): getting started\n"
            "- [Spec](spec/technical-spec.md): requirements\n"
            "```\n"
        ),
    )
    assert rules.check_references_resolve(doc) is None


def test_directive_pattern_ignores_prose_and_urls(tmp_path):
    """'file:'/'source:' inside ordinary prose must not smuggle a malformed
    duplicate reference (a stray leading '[' from an adjacent markdown link,
    or a truncated URL) into the extracted set \u2014 only the real markdown
    link should be captured."""
    skill_dir = tmp_path / "directiverefs"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "data.csv").write_text("a,b\n", encoding="utf-8")
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\nname: directiverefs\ndescription: Uses references. Use this skill when asked.\n---\n"
        "\nRefer to the example input file: [`data.csv`](data.csv).\n"
        "\nSee the source: <https://github.com/example/repo> for background.\n",
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
