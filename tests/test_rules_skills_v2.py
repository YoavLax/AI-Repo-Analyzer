"""Unit tests for the v0.2.0 skills-pillar additions (plan-v2-fable.md §4.2):

  skills.name.no-namespace, skills.disclosure.used,
  skills.disclosure.load-triggers, skills.scripts.non-interactive,
  skills.scripts.help, skills.coherence,

plus the metadata backfill (why/fix/effort/platforms) on every skills rule.

`skills.references.escape` was part of that release and has since been
withdrawn; what remains of it here is the test that keeps it withdrawn.
"""
from pathlib import Path

from airx import config, fs
from airx.discovery import build_index
from airx.model import Platform, RuleSource, Severity
from airx.parser import parse
from airx.rules import skills as rules
from airx.rules.registry import EFFORT_RANK, all_rules, get_rule

NEW_RULE_IDS = {
    "skills.name.no-namespace",
    "skills.disclosure.used",
    "skills.disclosure.load-triggers",
    "skills.scripts.non-interactive",
    "skills.scripts.help",
    "skills.coherence",
}


def _doc(tmp_path: Path, name: str, frontmatter_yaml: str, body: str = "\n# Body\n"):
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    raw = f"---\n{frontmatter_yaml}\n---\n{body}"
    path.write_text(raw, encoding="utf-8")
    return parse(path)


def _doc_with_scripts(tmp_path: Path, name: str, scripts: dict[str, str]):
    skill_dir = tmp_path / name
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    for fname, content in scripts.items():
        (skill_dir / "scripts" / fname).write_text(content, encoding="utf-8")
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: Runs bundled deployment scripts when asked.\n---\n\n# Body\n",
        encoding="utf-8",
    )
    return parse(path)


# --- skills.name.no-namespace ------------------------------------------------

def test_no_namespace_passes_for_plain_name(tmp_path):
    doc = _doc(tmp_path, "deploy-helper", "name: deploy-helper\ndescription: Deploys things when asked.")
    sat, diags = rules.check_name_no_namespace(doc)
    assert sat == 1.0
    assert diags == []


def test_no_namespace_flags_slash(tmp_path):
    doc = _doc(tmp_path, "x", "name: myorg/deploy\ndescription: Deploys things when asked.")
    sat, diags = rules.check_name_no_namespace(doc)
    assert sat == 0.0
    assert diags[0].severity == Severity.ERROR
    assert "/" in diags[0].message


def test_no_namespace_flags_colon(tmp_path):
    doc = _doc(tmp_path, "x", 'name: "plugin:deploy"\ndescription: Deploys things when asked.')
    sat, diags = rules.check_name_no_namespace(doc)
    assert sat == 0.0
    assert diags[0].severity == Severity.ERROR


def test_no_namespace_not_applicable_when_name_missing_or_non_string(tmp_path):
    missing = _doc(tmp_path, "a", "description: Deploys things when asked.")
    assert rules.check_name_no_namespace(missing) is None
    non_string = _doc(tmp_path, "b", "name: true\ndescription: Deploys things when asked.")
    assert rules.check_name_no_namespace(non_string) is None
    empty = _doc(tmp_path, "c", 'name: ""\ndescription: Deploys things when asked.')
    assert rules.check_name_no_namespace(empty) is None


# --- skills.references.* -----------------------------------------------------

def test_references_escape_rule_no_longer_exists():
    """`skills.references.escape` was withdrawn, and must not come back.

    It shipped as a SPEC-sourced ERROR at the skills pillar's highest weight,
    citing agentskills.io/specification#file-references for the claim that a
    skill must be self-contained, and CWE-59 for the claim that a `../` link is
    a link-following vulnerability. That section says exactly two things --
    "use relative paths from the skill root" and "Keep file references one
    level deep from `SKILL.md`" -- and neither is a prohibition. Across a
    35-repository corpus the rule produced 533 findings, every one of them an
    instruction to duplicate a deliberately shared file.
    """
    assert "skills.references.escape" not in {r.id for r in all_rules()}


def test_references_resolve_allows_a_link_to_a_sibling_skill(tmp_path):
    """The shape the withdrawn rule existed to punish, now expected to pass.

    Two skills sharing one reference file is ordinary authoring: the spec
    neither forbids it nor mentions it. The file exists, so there is nothing
    to report. Real shape: three such references in obra/superpowers.
    """
    other = tmp_path / "skills" / "using-superpowers" / "references"
    other.mkdir(parents=True)
    (other / "codex-tools.md").write_text("# Codex\n", encoding="utf-8")

    skill = tmp_path / "skills" / "writing-skills"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: writing-skills\ndescription: Use when authoring a new skill.\n---\n\n"
        "See [codex](../using-superpowers/references/codex-tools.md).\n",
        encoding="utf-8",
    )
    doc = parse(skill / "SKILL.md")
    sat, diags = rules.check_references_resolve(doc, build_index(fs.scan(tmp_path)))
    assert sat == 1.0
    assert diags == []


def test_references_resolve_flags_a_missing_file(tmp_path):
    doc = _doc(
        tmp_path, "refs",
        "name: refs\ndescription: Uses references when asked.",
        body="\nSee [missing](scripts/missing.sh).\n",
    )
    sat, diags = rules.check_references_resolve(doc, build_index(fs.scan(tmp_path)))
    assert sat == 0.0
    assert len(diags) == 1
    assert diags[0].severity == Severity.ERROR
    assert "does not exist" in diags[0].message


def test_references_resolve_ignores_root_relative_url_paths(tmp_path):
    """A '/docs/...'-style link is the web convention for a site-root-relative
    URL (e.g. https://nextjs.org/docs/...), not a filesystem reference, so it
    is never extracted in the first place."""
    doc = _doc(
        tmp_path, "refs-weburl",
        "name: refs-weburl\ndescription: Uses references when asked.",
        body="\nSee [the glossary](/docs/app/glossary.md).\n",
    )
    assert rules.check_references_resolve(doc, build_index(fs.scan(tmp_path))) is None


def test_references_resolve_ignores_targets_outside_the_repository(tmp_path):
    """`../../outside.txt` leaves the scanned tree, so the listing cannot say
    whether it exists. Silence is the honest answer, not an error."""
    doc = _doc(
        tmp_path, "refs-out",
        "name: refs-out\ndescription: Uses references when asked.",
        body="\nSee [outside](../../outside.txt).\n",
    )
    sat, diags = rules.check_references_resolve(doc, build_index(fs.scan(tmp_path)))
    assert sat == 1.0
    assert diags == []


def test_references_depth_ignores_parent_traversal(tmp_path):
    """`../` is sideways, not deep. The spec's advice is about nesting below
    SKILL.md; reporting a sibling link as a depth problem overstates it."""
    doc = _doc(
        tmp_path, "refs-depth",
        "name: refs-depth\ndescription: Uses references when asked.",
        body="\nSee [sibling](../other/notes.md) and [deep](a/b/c.md).\n",
    )
    sat, diags = rules.check_references_depth(doc)
    assert sat == 0.0
    assert len(diags) == 1
    assert "a/b/c.md" in diags[0].message


def test_reference_rule_weights_after_split():
    assert get_rule("skills.references.resolve").weight == 5


# --- skills.disclosure.used --------------------------------------------------

def test_disclosure_used_not_applicable_for_short_body(tmp_path):
    doc = _doc(tmp_path, "short", "name: short\ndescription: Does something when asked.")
    assert rules.check_disclosure_used(doc, build_index(fs.scan(tmp_path))) is None


def test_disclosure_used_flags_long_body_without_sibling_dirs(tmp_path):
    body = "\n" + ("Line of text.\n" * (config.DISCLOSURE_BODY_LINES + 5))
    doc = _doc(tmp_path, "long", "name: long\ndescription: Does something when asked.", body=body)
    sat, diags = rules.check_disclosure_used(doc, build_index(fs.scan(tmp_path)))
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO
    assert "references" in diags[0].message


def test_disclosure_used_passes_long_body_with_references_dir(tmp_path):
    body = "\n" + ("Line of text.\n" * (config.DISCLOSURE_BODY_LINES + 5))
    doc = _doc(tmp_path, "longref", "name: longref\ndescription: Does something when asked.", body=body)
    (tmp_path / "longref" / "references").mkdir()
    # An empty dir is invisible to fs.scan; only a dir with at least one
    # scan-visible file counts as progressive disclosure.
    (tmp_path / "longref" / "references" / "setup.md").write_text("Setup.\n", encoding="utf-8")
    sat, diags = rules.check_disclosure_used(doc, build_index(fs.scan(tmp_path)))
    assert sat == 1.0
    assert diags == []


def test_disclosure_used_passes_long_body_with_scripts_dir(tmp_path):
    body = "\n" + ("Line of text.\n" * (config.DISCLOSURE_BODY_LINES + 5))
    doc = _doc(tmp_path, "longscr", "name: longscr\ndescription: Does something when asked.", body=body)
    (tmp_path / "longscr" / "scripts").mkdir()
    (tmp_path / "longscr" / "scripts" / "run.sh").write_text("echo run\n", encoding="utf-8")
    sat, diags = rules.check_disclosure_used(doc, build_index(fs.scan(tmp_path)))
    assert sat == 1.0


# --- skills.disclosure.load-triggers -----------------------------------------

def test_load_triggers_not_applicable_without_references(tmp_path):
    doc = _doc(tmp_path, "norefs2", "name: norefs2\ndescription: Does something when asked.")
    assert rules.check_disclosure_load_triggers(doc) is None


def test_load_triggers_passes_when_reference_line_has_condition(tmp_path):
    doc = _doc(
        tmp_path, "trig",
        "name: trig\ndescription: Uses references when asked.",
        body="\nRead [debug](references/debug.md) when tests fail.\n",
    )
    sat, diags = rules.check_disclosure_load_triggers(doc)
    assert sat == 1.0
    assert diags == []


def test_load_triggers_passes_when_neighbor_line_has_condition(tmp_path):
    doc = _doc(
        tmp_path, "trig2",
        "name: trig2\ndescription: Uses references when asked.",
        body="\nWhen the build breaks:\nSee [debug](references/debug.md).\n",
    )
    sat, diags = rules.check_disclosure_load_triggers(doc)
    assert sat == 1.0


def test_load_triggers_flags_unconditional_references(tmp_path):
    doc = _doc(
        tmp_path, "notrig",
        "name: notrig\ndescription: Uses references on demand.",
        body="\nOverview of the tool.\n\nSee [details](references/details.md) and more.\n\nDone.\n",
    )
    sat, diags = rules.check_disclosure_load_triggers(doc)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO


# --- skills.scripts.non-interactive ------------------------------------------

def test_scripts_non_interactive_not_applicable_without_scripts_dir(tmp_path):
    doc = _doc(tmp_path, "noscripts", "name: noscripts\ndescription: Does something when asked.")
    assert rules.check_scripts_non_interactive(doc) is None


def test_scripts_non_interactive_flags_interactive_scripts_per_file(tmp_path):
    doc = _doc_with_scripts(tmp_path, "inter", {
        "ask.py": 'name = input("Name? ")\n',
        "ask.sh": 'read -p "Continue? " answer\n',
        "ok.py": 'import sys\nprint(sys.argv)\n',
    })
    sat, diags = rules.check_scripts_non_interactive(doc)
    assert sat == 0.0
    assert len(diags) == 2
    # Deterministic sorted order and per-file messages.
    assert "scripts/ask.py" in diags[0].message
    assert "scripts/ask.sh" in diags[1].message
    assert all(d.severity == Severity.WARNING for d in diags)


def test_scripts_non_interactive_passes_for_clean_scripts(tmp_path):
    doc = _doc_with_scripts(tmp_path, "clean", {
        "run.py": 'import sys\nprint(sys.argv)\n',
        "build.sh": 'set -e\nmake build\n',
    })
    sat, diags = rules.check_scripts_non_interactive(doc)
    assert sat == 1.0
    assert diags == []


# --- skills.scripts.help ------------------------------------------------------

def test_scripts_help_not_applicable_without_scripts_dir(tmp_path):
    doc = _doc(tmp_path, "noscripts2", "name: noscripts2\ndescription: Does something when asked.")
    assert rules.check_scripts_help(doc) is None


def test_scripts_help_passes_when_every_script_has_help_surface(tmp_path):
    doc = _doc_with_scripts(tmp_path, "helpful", {
        "run.py": "import argparse\nparser = argparse.ArgumentParser()\n",
        "build.sh": 'case "$1" in --help) usage ;; esac\n',
    })
    sat, diags = rules.check_scripts_help(doc)
    assert sat == 1.0
    assert diags == []


def test_scripts_help_flags_script_without_help_surface(tmp_path):
    doc = _doc_with_scripts(tmp_path, "unhelpful", {
        "run.py": 'print("hello")\n',
    })
    sat, diags = rules.check_scripts_help(doc)
    assert sat == 0.0
    assert len(diags) == 1
    assert diags[0].severity == Severity.INFO
    assert "scripts/run.py" in diags[0].message


# --- skills.coherence ---------------------------------------------------------

def test_coherence_not_applicable_when_description_missing_or_non_string(tmp_path):
    missing = _doc(tmp_path, "d1", "name: d1")
    assert rules.check_coherence(missing) is None
    non_string = _doc(tmp_path, "d2", "name: d2\ndescription: 12345")
    assert rules.check_coherence(non_string) is None


def test_coherence_flags_too_narrow_description(tmp_path):
    doc = _doc(tmp_path, "narrow", "name: narrow\ndescription: Helps with stuff.")
    sat, diags = rules.check_coherence(doc)
    assert sat == 0.0
    assert diags[0].severity == Severity.INFO
    assert "too narrow" in diags[0].message


def test_coherence_passes_rich_description(tmp_path):
    doc = _doc(
        tmp_path, "rich",
        "name: rich\n"
        "description: >-\n"
        "  Validates and deploys packaged releases to the staging environment,\n"
        "  verifies health checks, and rolls back failed deployments. Use this\n"
        "  skill whenever the user asks to deploy, ship, or release a build.\n",
    )
    sat, diags = rules.check_coherence(doc)
    assert sat == 1.0
    assert diags == []


# --- metadata backfill --------------------------------------------------------

def test_new_rules_are_registered():
    ids = {r.id for r in all_rules()}
    assert NEW_RULE_IDS <= ids


def test_every_skills_rule_carries_backfilled_metadata():
    skills_rules = [r for r in all_rules() if r.id.startswith("skills.")]
    assert len(skills_rules) == 36  # 30 pre-existing + 7 additions - references.escape
    for meta in skills_rules:
        assert meta.why, f"{meta.id} is missing why="
        assert meta.fix, f"{meta.id} is missing fix="
        assert meta.effort in EFFORT_RANK, f"{meta.id} has invalid effort {meta.effort!r}"
        # All skills rules keep the universal default platform tuple.
        assert meta.platforms == (Platform.COPILOT, Platform.CLAUDE), meta.id
