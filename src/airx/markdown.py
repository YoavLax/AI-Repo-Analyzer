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

#: A fenced code block, capturing its body.
CODE_BLOCK_RE = re.compile(r"^(?:```|~~~)[^\n]*\n(.*?)^(?:```|~~~)\s*$", re.MULTILINE | re.DOTALL)

#: A *relative* Markdown link target. Absolute (`/x`), external
#: (`https://`, `mailto:`) and pure `#anchor` links never match.
MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?!https?://|mailto:|/)([^)\s#]+)(?:#[^)]*)?\)")

#: A `source:` / `file:` / `include:` directive pointing at a companion file.
DIRECTIVE_RE = re.compile(
    r"(?:source|file|include):\s*([A-Za-z0-9_.\-/]+\.[a-zA-Z0-9]+)", re.IGNORECASE,
)

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


def extract_references(body: str) -> list[str]:
    """Companion-file references in `body`: relative Markdown links plus
    `source:`/`file:`/`include:` directives, de-duplicated, first-seen order.

    Fenced code blocks are stripped first (see `strip_code_blocks`).
    """
    body = strip_code_blocks(body)
    refs: list[str] = []
    refs.extend(MD_LINK_RE.findall(body))
    refs.extend(DIRECTIVE_RE.findall(body))
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
