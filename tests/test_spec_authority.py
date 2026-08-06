"""Guards for the class of bug this file is named after: a rule that asserts
something its own `doc_url` does not say.

Three of them shipped. `skills.references.escape` claimed the Agent Skills spec
required a skill to be self-contained and called a `../` link a CWE-59 link-
following vulnerability; the section it cited says only "use relative paths
from the skill root" and "Keep file references one level deep from `SKILL.md`".
`scoping.applyto.declared` made a missing `applyTo` an ERROR at weight 6, while
VS Code lists the field as Required: No and documents the omitted case as
working. `safety.settings.valid` failed unknown top-level keys against a
hand-maintained catalog of a page that grows every release.

They shared one shape: `source=RuleSource.SPEC` is the way past the advisory
gate, and nothing checked that the cited page agreed. `spec_quote` closes that
by making the author paste the sentence.
"""
from __future__ import annotations

import pytest

from airx import markdown as md
from airx.discovery import build_index
from airx.model import Applicability, Pillar, RuleSource, Severity
from airx.patterns import classify
from airx.rules import foundation
from airx.rules import skills as rules
from airx.rules.registry import RuleScope, all_rules, rule
from airx import fs


# --- the gate ----------------------------------------------------------------

@pytest.fixture
def scratch_registry():
    """Registration mutates a module-global. Without this, a rule declared by a
    test stays in `all_rules()` for the rest of the process — scored against
    every repository every later test analyzes, in a way that depends on test
    ordering."""
    from airx.rules import registry as reg

    before = dict(reg._REGISTRY)
    try:
        yield
    finally:
        reg._REGISTRY.clear()
        reg._REGISTRY.update(before)


def test_spec_sourced_error_without_a_quote_is_rejected_at_registration(scratch_registry):
    with pytest.raises(ValueError, match="spec_quote"):
        @rule(
            id="test.unsupported.claim", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
            applicability=Applicability.QUALITY, weight=6, severity=Severity.ERROR,
            source=RuleSource.SPEC, doc_url="https://example.invalid/spec",
            summary="Asserts something no sentence supports.",
        )
        def _check(index):  # pragma: no cover - never registered
            return 1.0, []


def test_spec_sourced_error_with_a_quote_registers(scratch_registry):
    from airx.rules.registry import get_rule

    @rule(
        id="test.supported.claim", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
        applicability=Applicability.QUALITY, weight=1, severity=Severity.INFO,
        source=RuleSource.SPEC, doc_url="https://example.invalid/spec",
        summary="Non-error rules need no quote.",
    )
    def _check(index):  # pragma: no cover - registration is the assertion
        return 1.0, []

    assert get_rule("test.supported.claim").severity is Severity.INFO


def test_every_spec_sourced_error_rule_cites_a_sentence():
    """The registry gate runs at import time, so this can only fail if the gate
    itself is weakened. That is the thing worth catching."""
    for meta in all_rules():
        if meta.source is RuleSource.SPEC and meta.severity is Severity.ERROR:
            assert meta.spec_quote, f"{meta.id} has no spec_quote"
            assert meta.doc_url, f"{meta.id} cites no document"
            assert len(meta.spec_quote) >= 20, (
                f"{meta.id}: {meta.spec_quote!r} is too short to be a sentence"
            )


def test_withdrawn_rules_stay_withdrawn():
    """Each was withdrawn for asserting a requirement its authority does not
    state. Re-adding one needs a sentence, not a preference."""
    ids = {m.id for m in all_rules()}
    assert "skills.references.escape" not in ids


# --- reference extraction ----------------------------------------------------

def test_a_file_uri_yields_one_reference_not_three():
    """`file:///Users/x/README.md` used to produce three findings from one
    link: the URI itself (MD_LINK_RE's scheme list did not cover `file:`), the
    `///Users/...` remainder (DIRECTIVE_RE matched the `file:` inside it), and
    nothing that resembled what the author wrote."""
    refs = md.extract_references("See [the guide](file:///Users/x/README.md).\n")
    assert refs == []


def test_placeholder_link_targets_are_not_references():
    body = "Read [the docs](URL) and [the ticket](TBD), then [notes](refs/n.md).\n"
    assert md.extract_references(body) == ["refs/n.md"]


def test_directives_are_not_read_out_of_link_urls():
    body = "Open [it](https://example.com/file:%20a.md) or use file: real.md\n"
    assert md.extract_references(body) == ["real.md"]


def test_inline_code_spans_are_not_references():
    body = "Write `[x](fake.md)` or `file: fake2.md` to show the syntax; see [r](real.md).\n"
    assert md.extract_references(body) == ["real.md"]


def test_real_references_still_survive_all_of_that():
    body = (
        "See [the reference guide](references/REFERENCE.md) for details.\n"
        "source: scripts/extract.py\n"
        "And a sibling: [sib](../other/notes.md), and a dir: [d](assets/).\n"
    )
    assert md.extract_references(body) == [
        "references/REFERENCE.md", "../other/notes.md", "assets/", "scripts/extract.py",
    ]


# --- CLAUDE.md imports -------------------------------------------------------

def _index_with_claude_md(tmp_path, text: str):
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    return build_index(fs.scan(tmp_path))


def test_import_inside_a_fenced_block_is_not_an_import(tmp_path):
    """"Import parsing skips Markdown code spans and fenced code blocks."
    A decorator in a Python example is not a broken import."""
    index = _index_with_claude_md(tmp_path, "# P\n\n```python\n@pytest.mark.parametrize\n```\n")
    assert foundation.check_imports_resolve(index) is None


def test_import_inside_backticks_is_not_an_import(tmp_path):
    """"To mention a path in your CLAUDE.md without importing it, wrap it in
    backticks" — the documented escape hatch, which we have to honor."""
    index = _index_with_claude_md(tmp_path, "# P\n\nMention `@docs/absent.md` without loading it.\n")
    assert foundation.check_imports_resolve(index) is None


def test_a_bare_handle_is_not_judged_as_an_import(tmp_path):
    """`@alice` in prose and `@README` as an import are indistinguishable. A
    missed import costs a point; an ERROR on someone's name is an accusation."""
    index = _index_with_claude_md(tmp_path, "# P\n\nAsk @alice before changing this.\n")
    assert foundation.check_imports_resolve(index) is None


def test_a_broken_path_import_is_still_an_error(tmp_path):
    index = _index_with_claude_md(tmp_path, "# P\n\n@docs/missing.md\n")
    sat, diags = foundation.check_imports_resolve(index)
    assert sat == 0.0
    assert "docs/missing.md" in diags[0][1].message


def test_a_resolvable_path_import_passes(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "present.md").write_text("# Present\n", encoding="utf-8")
    index = _index_with_claude_md(tmp_path, "# P\n\n@docs/present.md\n")
    assert foundation.check_imports_resolve(index) == (1.0, [])


# --- agent-directory documentation -------------------------------------------

def test_a_readme_in_the_agents_directory_is_not_an_agent():
    """Claude Code would fail to load it, but "add name and description
    frontmatter to your README" is not advice anyone should follow, and an
    ERROR is what we would be attaching to it."""
    from pathlib import PurePosixPath

    assert classify(PurePosixPath(".claude/agents/README.md")) is None
    assert classify(PurePosixPath(".github/agents/README.md")) is None
    kind, _ = classify(PurePosixPath(".claude/agents/reviewer.md"))
    assert kind.value == "agent"


# --- the gate, extended to every ERROR rule ----------------------------------

@pytest.fixture
def allowlisted(monkeypatch):
    """Let a test declare an advisory ERROR, the way the 13 real ones do.

    Without this the advisory-severity check fires first and the citation gate
    is never reached — which is exactly how the gap survived: every advisory
    ERROR went through `_ADVISORY_ERROR_ALLOWLIST` and was then asked for
    nothing at all.
    """
    from airx.rules import registry as reg

    monkeypatch.setattr(
        reg, "_ADVISORY_ERROR_ALLOWLIST",
        reg._ADVISORY_ERROR_ALLOWLIST | {"test.uncited.error", "test.objective.error"},
    )


def test_advisory_error_with_neither_citation_nor_basis_is_rejected(scratch_registry, allowlisted):
    """The first version of this gate asked only SPEC-sourced errors for a
    quote — 18 of 31 rules, and none of the population where the problem lived.
    `skills.name.reserved` and `skills.description.person-voice` both came
    through the allowlist door carrying nothing."""
    with pytest.raises(ValueError, match="what it rests on"):
        @rule(
            id="test.uncited.error", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
            applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
            source=RuleSource.ADVISORY, doc_url="https://example.invalid/page",
            summary="An advisory error with nothing behind it.",
        )
        def _check(index):  # pragma: no cover - never registered
            return 1.0, []


def test_error_rule_may_rest_on_an_objective_basis(scratch_registry, allowlisted):
    """Some errors need no specification: JSON that does not parse is not a
    matter of opinion. They say so in one sentence instead of citing a page."""
    from airx.rules.registry import get_rule

    @rule(
        id="test.objective.error", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
        applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
        source=RuleSource.ADVISORY, doc_url="https://example.invalid/page",
        summary="An advisory error resting on an observation.",
        objective_basis="The file is not parseable JSON, so nothing in it takes effect.",
    )
    def _check(index):  # pragma: no cover - registration is the assertion
        return 1.0, []

    assert get_rule("test.objective.error").objective_basis


def test_an_error_rule_may_not_claim_both(scratch_registry):
    """Which one a rule rests on should be unambiguous to a reviewer."""
    with pytest.raises(ValueError, match="not both"):
        @rule(
            id="test.both.error", pillar=Pillar.SKILLS, scope=RuleScope.REPO,
            applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
            source=RuleSource.SPEC, doc_url="https://example.invalid/page",
            summary="Cites a sentence and an observation.",
            spec_quote="The value must be a string of 1-64 characters.",
            objective_basis="The value is not a string.",
        )
        def _check(index):  # pragma: no cover - never registered
            return 1.0, []


def test_every_error_rule_says_what_it_rests_on():
    """Import-time enforcement means this can only fail if the gate is
    weakened. That is exactly what is worth catching."""
    for meta in all_rules():
        if meta.severity is not Severity.ERROR:
            continue
        basis = meta.spec_quote or meta.objective_basis
        assert basis, f"{meta.id} is an ERROR resting on nothing"
        assert len(basis) >= 20, f"{meta.id}: {basis!r} is too short to be a reason"
        assert not (meta.spec_quote and meta.objective_basis), (
            f"{meta.id} claims both a citation and an observation"
        )
        if meta.spec_quote:
            assert meta.doc_url, f"{meta.id} quotes a sentence from nowhere"


def test_name_reserved_stays_withdrawn():
    """`skills.name.reserved` failed any name containing "claude" or
    "anthropic", as an ERROR, citing the spec's name-field section — which
    states five constraints on `name` and no reserved-word clause. It fired on
    `claude-api`, in Anthropic's own skills repository, which loads."""
    assert "skills.name.reserved" not in {m.id for m in all_rules()}


# --- bundled scripts ---------------------------------------------------------

def _skill_with_scripts(tmp_path, files: dict[str, str]):
    from airx.parser import parse

    skill = tmp_path / "packer"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: packer\ndescription: Packs things. Use this skill when packing.\n---\n\n# Body\n",
        encoding="utf-8",
    )
    for rel, text in files.items():
        p = skill / "scripts" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return parse(skill / "SKILL.md")


def test_data_files_under_scripts_are_not_scripts(tmp_path):
    """An XML Schema has no `--help` and never will. anthropics/skills bundles
    102 of them plus 9 `__init__.py` markers under one `scripts/` directory,
    which is 118 of the 158 findings we reported against that repository."""
    doc = _skill_with_scripts(tmp_path, {
        "schemas/dml-chart.xsd": "<xsd:schema/>\n",
        "data/lookup.json": "{}\n",
        "notes.txt": "notes\n",
        "__init__.py": "",
        "helpers/__init__.py": "",
    })
    assert rules.check_scripts_help(doc) == (1.0, [])
    assert rules.check_scripts_non_interactive(doc) == (1.0, [])


def test_a_real_script_without_help_is_still_reported(tmp_path):
    doc = _skill_with_scripts(tmp_path, {"extract.py": "print('no parser here')\n"})
    sat, diags = rules.check_scripts_help(doc)
    assert sat == 0.0
    assert "extract.py" in diags[0].message


def test_an_extensionless_script_counts(tmp_path):
    """An extensionless file under `scripts/` is what an executable looks like.
    obra/superpowers ships three."""
    doc = _skill_with_scripts(tmp_path, {"build": "#!/bin/sh\necho hi\n"})
    sat, diags = rules.check_scripts_help(doc)
    assert sat == 0.0
    assert "build" in diags[0].message


def test_the_executable_bit_never_changes_the_verdict(tmp_path):
    """D3: one commit, one answer, however the tree was obtained.

    The permission bit is a property of the filesystem, not of the commit.
    `git clone` restores it; the clone-free ingest writes fetched bytes with
    default permissions and cannot. A rule that consults it scores the same sha
    differently online and from a checkout — obra/superpowers read 56.39 from a
    clone and 56.47 from the API, and the gap was three extensionless scripts.
    """
    doc = _skill_with_scripts(tmp_path, {"runner": "#!/bin/sh\necho hi\n"})
    script = tmp_path / "packer" / "scripts" / "runner"

    script.chmod(0o644)
    without_bit = rules.check_scripts_help(doc)
    script.chmod(0o755)
    with_bit = rules.check_scripts_help(doc)

    assert without_bit == with_bit
    assert without_bit[0] == 0.0  # and it is judged, not merely judged equally


def test_a_scripts_directory_of_pure_data_is_applicable_and_clean(tmp_path):
    """`None` and `(1.0, [])` are different answers: no scripts directory means
    the rule does not apply, while a directory holding only data means it
    applies and passes. Collapsing them would hide the second case."""
    from airx.parser import parse

    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "SKILL.md").write_text(
        "---\nname: bare\ndescription: Does things. Use this skill when asked.\n---\n\n# Body\n",
        encoding="utf-8",
    )
    assert rules.check_scripts_help(parse(bare / "SKILL.md")) is None

    doc = _skill_with_scripts(tmp_path, {"data/lookup.json": "{}\n"})
    assert rules.check_scripts_help(doc) == (1.0, [])


# --- skill discovery ---------------------------------------------------------

def test_a_skill_directory_need_not_sit_under_one_named_skills():
    """"A skill is a directory containing, at minimum, a `SKILL.md` file."

    Requiring the grandparent to be literally named `skills` made
    anthropics/skills' top-level `template/SKILL.md` invisible — 17 of 18
    discovered, and every defect in the 18th unreportable at the discovery
    layer, where no rule-level check can reach it.
    """
    from pathlib import PurePosixPath

    for path in (".claude/skills/deploy/SKILL.md", "skills/deploy/SKILL.md",
                 "template/SKILL.md", "packages/web/.claude/skills/x/SKILL.md"):
        kind, _ = classify(PurePosixPath(path))
        assert kind.value == "skill", path


def test_a_root_level_skill_md_is_still_not_a_skill():
    """Its skill directory would be the checkout directory, whose name belongs
    to the machine rather than the tree — `skills.name.dirname-match` would
    then score one commit differently in two clones (determinism contract D1)."""
    from pathlib import PurePosixPath

    assert classify(PurePosixPath("SKILL.md")) is None


def test_a_file_named_like_an_excluded_directory_is_still_a_file(tmp_path):
    """`_visible_files` promises to agree with `fs.scan`, and did not: it
    tested every path component against the excluded-*directory* names, so
    `scripts/build` disappeared while `fs.scan` kept it. Same distinction
    `airx.ingest._safe_rel_path` already draws."""
    from airx.rules.skills import _visible_files

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("build", "dist", "run.sh"):
        (scripts / name).write_text("#!/bin/sh\n", encoding="utf-8")
    (scripts / "node_modules").mkdir()
    (scripts / "node_modules" / "pkg.js").write_text("//\n", encoding="utf-8")

    seen = {p.name for p in _visible_files(scripts)}
    assert seen == {"build", "dist", "run.sh"}

    scanned = {p.as_posix() for p in fs.scan(tmp_path).files}
    assert {"scripts/build", "scripts/dist", "scripts/run.sh"} <= scanned
    assert not any(p.startswith("scripts/node_modules/") for p in scanned)
