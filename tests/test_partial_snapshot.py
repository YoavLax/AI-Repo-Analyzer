"""The invariant that keeps a fetch budget from becoming a repository defect.

A clone-free snapshot lists every file in the repository but materializes only
the subset a fetch budget allowed. Before `RepoTree.materialized` existed, the
missing bytes surfaced as `FileNotFoundError` inside the artifact parsers,
which recorded them as `parse_error` — indistinguishable from malformed YAML.
One real scan of a large skills repository produced 70 `skills.parses` errors
reading "No such file or directory", every one of them an accusation against a
file that is perfectly valid in the repository.

The test at the bottom of this module is the lock: no finding may reference a
path this snapshot never read. It is deliberately written against the whole
scored report rather than any one rule, so a rule added years from now is
covered without anybody remembering this failure mode.
"""
from pathlib import Path, PurePosixPath

import pytest

import airx.rules  # noqa: F401  — registers every rule with the engine
from airx import fs
from airx.discovery import build_index
from airx.fs import RepoTree
from airx.scoring import score

#: Artifacts written as genuinely broken files. Held back from `materialized`
#: they must produce no finding at all; materialized, the same bytes must still
#: be caught — which is what proves the fix suppresses missing *coverage* and
#: not missing *quality*.
BROKEN = {
    "skills/alpha/SKILL.md": "---\nname: alpha\ndescription: [unclosed\n---\n\n# Alpha\n",
    "skills/beta/SKILL.md": "---\nname: beta\ndesc: x: y: z\n---\n\n# Beta\n",
    ".github/instructions/py.instructions.md": "---\napplyTo: [oops\n---\n\n# Python\n",
    ".claude/agents/reviewer.md": "---\nname: reviewer\ntools: [a\n---\n\n# Reviewer\n",
    ".claude/settings.json": '{"permissions": ',
    ".github/hooks/pre-commit.json": "{not json",
    ".mcp.json": "{not json either",
    ".github/prompts/review.prompt.md": "---\nmode: [oops\n---\n\n# Review\n",
    ".claude/commands/deploy.md": "---\ndescription: a: b: c\n---\n\n# Deploy\n",
    "GEMINI.md": "---\nfoo: [bar\n---\n\n# Gemini\n",
    "docs/AGENTS.md": "---\nx: [y\n---\n\n# Docs agents\n",
}

#: The subset of BROKEN that some rule actually reports today. Prompt files,
#: slash commands, and nested AGENTS.md are parsed but no rule surfaces their
#: parse failures, so the positive control below cannot assert on them — a gap
#: in rule coverage, unrelated to snapshot coverage.
REPORTED_WHEN_READ = frozenset({
    "skills/alpha/SKILL.md",
    "skills/beta/SKILL.md",
    ".github/instructions/py.instructions.md",
    ".claude/agents/reviewer.md",
    ".claude/settings.json",
    ".github/hooks/pre-commit.json",
    ".mcp.json",
    "GEMINI.md",
})

#: A minimum of valid material, so the pillars have something to score and the
#: repository does not look empty (an empty repo exercises far fewer rules).
SOUND = {
    "CLAUDE.md": "# Project\n\n- Run `pytest -q` before pushing.\n- Keep modules small.\n",
    ".github/copilot-instructions.md": "# Guidelines\n\n- Prefer explicit names.\n",
    "skills/gamma/SKILL.md": (
        "---\nname: gamma\ndescription: Use when formatting release notes for a tagged build.\n---\n\n"
        "# Gamma\n\n## Steps\n\n1. Collect merged PR titles.\n2. Group them by label.\n"
    ),
    "README.md": "# Demo\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for rel, text in {**SOUND, **BROKEN}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _tree(root: Path, withheld: frozenset[PurePosixPath]) -> RepoTree:
    """The repository as a partial snapshot: full listing, reduced coverage.

    The withheld files stay on disk on purpose. A test that simply deleted them
    would pass even if a rule fell back to reading the filesystem directly, so
    leaving them readable is what makes `materialized` the thing under test.
    """
    full = fs.scan(root)
    return RepoTree(
        root=full.root,
        files=full.files,
        materialized=frozenset(full.files) - withheld,
    )


def _findings(tree: RepoTree):
    """Every (path, Diagnostic) the scored report would show."""
    card = score(build_index(tree))
    return [
        (path, diag)
        for ev in card.evaluations
        if not ev.waived
        for path, diag in ev.diagnostics
    ]


BROKEN_PATHS = frozenset(PurePosixPath(p) for p in BROKEN)


# --- the mechanism -----------------------------------------------------------

def test_full_checkout_has_unbounded_coverage(repo: Path):
    # fs.scan models a real checkout, where every listed file is readable.
    assert fs.scan(repo).materialized is None
    assert fs.scan(repo).has_content(PurePosixPath("CLAUDE.md"))


def test_withheld_artifact_is_not_analyzed_rather_than_broken(repo: Path):
    index = build_index(_tree(repo, BROKEN_PATHS))
    withheld = [a for a in index.artifacts if a.rel_path in BROKEN_PATHS]
    assert len(withheld) == len(BROKEN), "every broken artifact should still be discovered"
    for artifact in withheld:
        # Discovered (so presence rules still see it), but with nothing claimed
        # about its contents.
        assert artifact.not_analyzed is True, artifact.rel_path
        assert artifact.parse_error is None, artifact.rel_path
        assert artifact.doc is None, artifact.rel_path
        assert artifact.json_data is None, artifact.rel_path


def test_withheld_skill_leaves_the_parse_rule_alone(repo: Path):
    # skills.parses is the rule that produced the 70 false errors.
    index = build_index(_tree(repo, BROKEN_PATHS))
    assert index.skill_parse_errors == ()
    assert len(index.skills) == 1  # only the sound one was read


# --- the positive control ----------------------------------------------------

def test_same_bytes_are_still_caught_when_materialized(repo: Path):
    """Coverage suppresses findings; it must not suppress defects.

    With nothing withheld, the identical files must still be reported — so a
    future change cannot make this whole class of finding disappear and still
    pass the invariant test below.
    """
    found = _findings(_tree(repo, frozenset()))
    missed = sorted(
        rel for rel in map(PurePosixPath, REPORTED_WHEN_READ)
        # Some rules attribute by path, others (skills.parses) name the file in
        # the message text only; either counts as reporting it.
        if not any(path == rel or str(rel) in diag.message for path, diag in found)
    )
    assert not missed, f"broken files went unreported when fully materialized: {missed}"


# --- the invariant -----------------------------------------------------------

def test_no_finding_references_an_unread_path(repo: Path):
    """No finding may point at a path outside the snapshot's coverage.

    This is the guard that makes the fix permanent. It is indifferent to *why*
    a file was not materialized — fetch budget today, an LFS pointer, a
    submodule, a symlink, or a mid-fetch network failure tomorrow — and it
    applies to rules that do not exist yet.
    """
    tree = _tree(repo, BROKEN_PATHS)
    offenders = [
        (path, diag.rule_id, diag.message)
        for path, diag in _findings(tree)
        if path is not None and not tree.has_content(path)
    ]
    assert not offenders, (
        "findings reference paths this snapshot never read:\n"
        + "\n".join(f"  {p} — {rule}: {msg}" for p, rule, msg in offenders)
    )


def test_existence_is_answered_from_the_listing_not_the_disk(tmp_path: Path):
    """The second shape of the same bug, and the more expensive one.

    Rules that probed the filesystem with `Path.is_file()` reported every
    reference into a not-yet-fetched directory as broken — 356 of them in one
    real scan of github/awesome-copilot, because the extra files inside a skill
    directory are the first thing a constrained fetch drops. Existence must be
    read off the pinned listing, which covers the whole repository whatever the
    budget was.
    """
    body = "Line of guidance.\n" * 400  # long enough to engage disclosure.used
    skill = tmp_path / "skills" / "delta"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: delta\ndescription: Use when reconciling a ledger against a bank export.\n---\n\n"
        f"# Delta\n\nSee [setup](references/setup.md) and [absent](references/absent.md).\n\n{body}",
        encoding="utf-8",
    )
    (skill / "references" / "setup.md").write_text("# Setup\n", encoding="utf-8")

    # Everything under references/ is listed but unfetched — the exact shape a
    # fetch budget produces, since those files rank last.
    withheld = frozenset({PurePosixPath("skills/delta/references/setup.md")})
    messages = [diag.message for _, diag in _findings(_tree(tmp_path, withheld))]

    assert not [m for m in messages if "references/setup.md" in m], (
        "a listed-but-unfetched reference was reported as broken"
    )
    assert [m for m in messages if "references/absent.md" in m], (
        "a genuinely missing reference must still be reported"
    )
    assert not [m for m in messages if "progressive disclosure" in m], (
        "a references/ directory whose files went unfetched is still a "
        "references/ directory"
    )


def test_no_finding_blames_the_repository_for_a_missing_file(repo: Path):
    """A path-free diagnostic can leak the same accusation through its text.

    `_error_text` renders OSError as "FileNotFoundError: No such file or
    directory", so this catches the message even where the path attribution is
    absent or points somewhere else.
    """
    leaks = [
        (path, diag.rule_id, diag.message)
        for path, diag in _findings(_tree(repo, BROKEN_PATHS))
        if "No such file" in diag.message or "FileNotFoundError" in diag.message
    ]
    assert not leaks, "\n".join(f"  {p} — {rule}: {msg}" for p, rule, msg in leaks)
