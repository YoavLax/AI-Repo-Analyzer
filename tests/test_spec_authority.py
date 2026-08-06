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
