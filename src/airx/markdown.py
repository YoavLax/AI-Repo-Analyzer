"""Markdown primitives shared by the rule pillars and the clone-free ingest.

These live outside `airx.rules` on purpose. `airx.ingest` has to resolve
*exactly* the references the rules go on to read: if the online scan fetched a
different set of files than the rules load, the same commit would score
differently in the web app than on the CLI (determinism contract D3). One
definition makes that drift impossible instead of merely unlikely.

Everything here is a pure function of its input text — no filesystem access, no
ordering dependence — so callers decide which resolved targets actually exist.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath

#: A fenced code block, capturing its body. The fence markers may carry
#: leading whitespace (a fence nested under a list item, e.g. "   ```bash",
#: is still a fence) — matching only column-0 fences left indented examples
#: unstripped, so their contents were scanned as if they were live prose.
CODE_BLOCK_RE = re.compile(r"^[ \t]*(?:```|~~~)[^\n]*\n(.*?)^[ \t]*(?:```|~~~)[ \t]*$", re.MULTILINE | re.DOTALL)

#: A *relative* Markdown link target. Absolute (`/x`) and pure `#anchor` links
#: never match, and neither does anything carrying a URI scheme.
#:
#: The scheme guard is general (`[a-zA-Z][a-zA-Z0-9+.-]*:`) rather than a list
#: of known schemes. Enumerating `https?://|mailto:` let `file:///Users/x/R.md`
#: through as a *relative* target, and then `DIRECTIVE_RE` matched the `file:`
#: inside it a second time — one link in one repository produced three separate
#: findings, two of them about paths that were never written.
MD_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\((?![a-zA-Z][a-zA-Z0-9+.\-]*:|/)([^)\s#]+)(?:#[^)]*)?\)"
)

#: Any Markdown link, whatever its target. Used to blank link syntax out of the
#: text before directive scanning, so a link's URL can never be read as prose.
ANY_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")

#: An ATX heading line ("#" through "######"). A heading is a title/label —
#: "### Primary Working File: notes.md" names a file the section is *about*,
#: not a directive to load it — so headings are blanked out before directive
#: scanning the same way link syntax is, without touching the identical
#: phrase were it written as ordinary paragraph prose.
HEADING_LINE_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+.*$", re.MULTILINE)

#: A `source:` / `file:` / `include:` directive pointing at a companion file.
DIRECTIVE_RE = re.compile(
    r"(?:source|file|include):\s*([A-Za-z0-9_.\-/]+\.[a-zA-Z0-9]+)", re.IGNORECASE,
)

#: An inline code span. Backtick-quoted text is how authors *mention* a path
#: without linking it, which is why Claude Code's own import parser skips code
#: spans ("To mention a path in your CLAUDE.md without importing it, wrap it in
#: backticks" — code.claude.com/docs/en/memory#import-additional-files).
CODE_SPAN_RE = re.compile(r"(`+)(?:(?!\1).)*?\1", re.DOTALL)

#: Prose that gates *when* a companion file should be read, e.g.
#: "Read docs/testing.md when writing new tests."
LOAD_TRIGGER_RE = re.compile(r"(?:when|if|read .* (?:for|when|if)|run .* when)", re.IGNORECASE)


def strip_code_blocks(body: str) -> str:
    """`body` with every fenced code block removed.

    Fenced blocks commonly hold illustrative example syntax — a template for a
    *generated* file, a sample CLI invocation, a Markdown snippet being taught —
    rather than live directives the agent should follow. Scanning them for
    references produces links to files that were never meant to exist, and (via
    ingest) network fetches for them.
    """
    return CODE_BLOCK_RE.sub("", body)


def strip_code(body: str) -> str:
    """`body` with fenced blocks *and* inline code spans removed.

    Both are how authors quote syntax rather than invoke it. Claude Code's
    import parser draws the same line, and a path in backticks is the
    documented way to name a file without loading it.
    """
    return CODE_SPAN_RE.sub(" ", strip_code_blocks(body))


def is_file_like(ref: str) -> bool:
    """Whether `ref` names a file rather than a placeholder.

    `[the guide](URL)`, `[see](TBD)` and `[docs](path/to/file)` are templates
    and prose, not companion files: resolving them produces findings about
    paths no author ever intended to exist. A real reference carries an
    extension on its last segment, or is a directory.
    """
    if ref.endswith("/"):
        return True
    return "." in ref.rsplit("/", 1)[-1]


def extract_references(body: str) -> list[str]:
    """Companion-file references in `body`: relative Markdown links plus
    `source:`/`file:`/`include:` directives, de-duplicated, first-seen order.

    Fenced code blocks and inline code spans are stripped first, link syntax
    and heading lines are blanked out before directives are scanned, and
    targets that do not name a file are dropped (see `strip_code`,
    `ANY_LINK_RE`, `HEADING_LINE_RE`, `is_file_like`).
    """
    body = strip_code(body)
    refs: list[str] = []
    refs.extend(MD_LINK_RE.findall(body))
    # Directives are paragraph prose. Scanning link syntax for them reads a
    # link's URL as if the author had written it as a directive, and scanning
    # heading text reads a section title's own filename mention the same way.
    directive_source = HEADING_LINE_RE.sub(" ", ANY_LINK_RE.sub(" ", body))
    refs.extend(DIRECTIVE_RE.findall(directive_source))
    refs = [r for r in refs if is_file_like(r)]
    seen: set[str] = set()
    unique: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def referenced_markdown(text: str, from_rel: PurePosixPath) -> tuple[PurePosixPath, ...]:
    """Repo-relative `.md` targets linked from `from_rel`'s text, resolved
    against its directory, de-duplicated, in stable sorted order.

    Absolute, external, non-Markdown and repo-escaping links are dropped, as are
    links inside fenced code blocks. The caller decides which of the remaining
    targets actually exist.
    """
    targets: set[str] = set()
    for ref in MD_LINK_RE.findall(strip_code_blocks(text)):
        if not ref.endswith(".md"):
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel.as_posix()), ref))
        if target.startswith(".."):
            continue
        targets.add(target)
    return tuple(PurePosixPath(t) for t in sorted(targets))
