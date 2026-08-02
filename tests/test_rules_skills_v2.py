"""Unit tests for the v0.2.0 skills-pillar additions (plan-v2-fable.md §4.2):

  skills.name.no-namespace, skills.references.escape, skills.disclosure.used,
  skills.disclosure.load-triggers, skills.scripts.non-interactive,
  skills.scripts.help, skills.coherence,

plus the metadata backfill (why/fix/effort/platforms) on every skills rule and
the references.resolve weight split (6 -> 5, with escape at 6).
"""
from pathlib import Path

from airx import config
from airx.model import Platform, RuleSource, Severity
from airx.parser import parse
from airx.rules import skills as rules
from airx.rules.registry import EFFORT_RANK, all_rules, get_rule

NEW_RULE_IDS = {
    "skills.name.no-namespace",
    "skills.references.escape",
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


# --- skills.references.escape ------------------------------------------------

def test_references_escape_passes_for_in_dir_reference(tmp_path):
    # Existence is irrelevant here — only escaping matters.
    doc = _doc(
        tmp_path, "refs-ok",
        "name: refs-ok\ndescription: Uses references when asked.",
        body="\nSee [notes](references/notes.md) and more.\n",
    )
    sat, diags = rules.check_references_escape(doc)
    assert sat == 1.0
    assert diags == []


def test_references_escape_flags_escaping_reference(tmp_path):
    doc = _doc(
        tmp_path, "refs-bad",
        "name: refs-bad\ndescription: Uses references when asked.",
        body="\nSee [outside](../../outside.txt) and [inside](notes.md).\n",
    )
    sat, diags = rules.check_references_escape(doc)
    assert sat == 0.0
    assert len(diags) == 1
    assert diags[0].severity == Severity.ERROR
    assert "../../outside.txt" in diags[0].message


def test_references_escape_not_applicable_without_references(tmp_path):
    doc = _doc(tmp_path, "norefs", "name: norefs\ndescription: Does something when asked.")
    assert rules.check_references_escape(doc) is None


def test_references_escape_ignores_root_relative_url_paths(tmp_path):
    """A '/docs/...'-style link is the standard web convention for a
    site-root-relative URL (e.g. https://nextjs.org/docs/...), not a
    filesystem reference \u2014 it must not be flagged as escaping the skill
    directory (CWE-59)."""
    doc = _doc(
        tmp_path, "refs-weburl",
        "name: refs-weburl\ndescription: Uses references when asked.",
        body="\nSee [the glossary](/docs/app/glossary) and [notes](notes.md).\n",
    )
    sat, diags = rules.check_references_escape(doc)
    assert sat == 1.0
    assert diags == []


def test_references_resolve_still_flags_escaping_ref_as_unresolvable(tmp_path):
    """The split keeps resolve reporting an escaping ref (it cannot exist inside
    the dir), so the historical two-diagnostic behavior is preserved."""
    doc = _doc(
        tmp_path, "refs",
        "name: refs\ndescription: Uses references when asked.",
        body="\nSee [missing](scripts/missing.sh) and [outside](../../outside.txt).\n",
    )
    sat, diags = rules.check_references_resolve(doc)
    assert sat == 0.0
    assert len(diags) == 2
    assert any("resolves outside the skill directory" in d.message for d in diags)
    assert any("does not exist" in d.message for d in diags)


def test_reference_rule_weights_after_split():
    assert get_rule("skills.references.resolve").weight == 5
    escape = get_rule("skills.references.escape")
    assert escape.weight == 6
    assert escape.severity == Severity.ERROR
    assert escape.source == RuleSource.SPEC


# --- skills.disclosure.used --------------------------------------------------

def test_disclosure_used_not_applicable_for_short_body(tmp_path):
    doc = _doc(tmp_path, "short", "name: short\ndescription: Does something when asked.")
    assert rules.check_disclosure_used(doc) is None


def test_disclosure_used_flags_long_body_without_sibling_dirs(tmp_path):
    body = "\n" + ("Line of text.\n" * (config.DISCLOSURE_BODY_LINES + 5))
    doc = _doc(tmp_path, "long", "name: long\ndescription: Does something when asked.", body=body)
    sat, diags = rules.check_disclosure_used(doc)
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
    sat, diags = rules.check_disclosure_used(doc)
    assert sat == 1.0
    assert diags == []


def test_disclosure_used_passes_long_body_with_scripts_dir(tmp_path):
    body = "\n" + ("Line of text.\n" * (config.DISCLOSURE_BODY_LINES + 5))
    doc = _doc(tmp_path, "longscr", "name: longscr\ndescription: Does something when asked.", body=body)
    (tmp_path / "longscr" / "scripts").mkdir()
    (tmp_path / "longscr" / "scripts" / "run.sh").write_text("echo run\n", encoding="utf-8")
    sat, diags = rules.check_disclosure_used(doc)
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
    assert len(skills_rules) == 37  # 30 pre-existing + 7 additions
    for meta in skills_rules:
        assert meta.why, f"{meta.id} is missing why="
        assert meta.fix, f"{meta.id} is missing fix="
        assert meta.effort in EFFORT_RANK, f"{meta.id} has invalid effort {meta.effort!r}"
        # All skills rules keep the universal default platform tuple.
        assert meta.platforms == (Platform.COPILOT, Platform.CLAUDE), meta.id
