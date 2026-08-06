# Opening a PR on someone else's repository

How we turn an AgentCompass finding into a pull request a maintainer wants to
merge. The goal is a contribution that stands on its own; that people come to
know the tool is a consequence of the contribution being good, never its
purpose.

One rule sits above the rest:

> **The fix is the subject. The tool is a footnote.**

A PR that opens with a score reads as judgment. A PR that opens with a
one-line bug and closes with "here's how I found it" reads as help. Same
information, opposite reception.

## What qualifies

A finding earns a PR only if **all five** hold:

1. **Objective.** The claim is true independent of our scoring — a spec, a
   vendor doc, or a parser says so. "Our analyzer flags it" is not a reason.
2. **Citable.** There is a URL to the authority, and the quoted spelling or
   requirement is visible on that page.
3. **Small.** The diff fits on one screen. A reviewer should finish it faster
   than they could ask a question about it.
4. **Reproducible without us.** The maintainer can confirm it with `grep`, a
   parser, or their own eyes. Never make merging depend on trusting our tool.
5. **Not a matter of taste.** If a reasonable maintainer could have chosen it
   on purpose, it is not a bug. Leave it alone.

Severity is a filter, not a certificate: most `error` findings qualify, most
`warning` findings need a second look, `info` findings never do.

### Exactly one fix per PR

Not "few". **One.** When several findings qualify, take the single
best-evidenced one and leave the rest — even when the others are real, even
when fixing them is equally cheap.

Two unrelated fixes double the reasons to say no, need different reviewers, and
turn a ten-second merge into a discussion. Worse, a PR carrying a spread of
changes reads as a sweep run by a tool rather than a person who found something.
The one that lands buys the standing to open the next.

Rank the candidates by how hard the claim is to argue with — a vendor doc
quoting the exact spelling beats a spec paraphrase, which beats a parser error,
which beats our own rule. Take the top one. Open the second only after the
first is merged.

## What never goes in

- The overall score, the grade, or the pillar breakdown in the opening section
- A full-report screenshot — it reads as an advertisement
- Findings the PR does not fix ("while I was here, I also noticed…")
- Any ask: no star request, no feedback request, no "let me know what you think"
- Our roadmap, our other features, or comparisons to other tools

## Template

Replace every `<…>`. Delete any section that would be padding for this
particular fix — a three-character change does not need a Testing section.

---

```markdown
### What

<One or two sentences. The concrete defect and where it is. No preamble.>

### Why it matters

<The user-visible consequence, in terms of the repository's own users. Not
"this lowers your score" — what actually breaks, silently or otherwise.>

<Then the citation, quoted: the docs spell the field `x`, the spec requires y.
Link directly to the anchor, not the doc root.>

### Verification

<A command the maintainer can run in their own checkout, with its real output.
This is what makes the PR self-contained.>

```
$ <command>
<real output>
```

### How I found it

Running the repo through [AgentCompass](<repo-url>), a deterministic static
analyzer that scores how ready a repository is for AI coding agents. It flagged
this as `<rule.id>`.

Reproduce it without installing anything: <deep-link>/?repo=<owner>/<name>

<One cropped screenshot of these findings only — never the whole findings
table. Use `scripts/focus-shot.js` to clip to the matching rows.>

<The score summary band, `dark-summary.png` from `capture.js`.>

<sub><img src="https://raw.githubusercontent.com/YoavLax/agent-compass/main/agentcompass.png" width="200" alt="AgentCompass"></sub>
```

---

### Two images, both below "How I found it"

**The findings crop** is the evidence: the rows this PR fixes, and nothing else.
`scripts/focus-shot.js` clips to them.

**The score summary band** is the context: grade, platform scores, findings
count. It goes immediately after the crop and immediately before the logo.

Position is the whole argument for the second one. A grade at the top of a PR
on someone else's repository says *we assessed you and here is your mark* — a
verdict the reader did not ask for, delivered before they have seen the fix. The
same band under the attribution reads as what the tool produced, which is what
the section is about. Never move it up, never put it in the `### What` section,
never mention the number in prose.

Neither image is ever the full report.

### The logo goes at the bottom, at 200px

A branded banner at the top of a PR on someone else's repository announces that
the PR is an outreach exercise before the reader reaches the fix — which is the
one impression this whole document exists to avoid. The same image as a small
mark under the attribution line is the convention every automated contributor
follows, and nobody objects to it.

So: footer, after "How I found it", `width="200"`, wrapped in `<sub>`. Never a
full-width banner, never above the diff, never twice.

The `src` must be the raw URL on our default branch, since a relative path
resolves against *their* repository and renders broken. Confirm it loads before
opening:

```
curl -sI https://raw.githubusercontent.com/YoavLax/agent-compass/main/agentcompass.png | head -1
```

## Commit message

Same discipline. The subject line names the fix, not the tool, and the tool is
not mentioned in the commit at all — it belongs in the PR description, which is
conversation, not history.

```
fix(<area>): <what changed, imperative>

<Why the old form was wrong, and what the authority says. Two or three lines.>
```

## Before opening

- [ ] Diff contains only the one fix — no formatting drift, no stray files
- [ ] Exactly one concern; every other qualifying finding was left out
- [ ] Every claim in the body is verifiable without running our tool
- [ ] The citation link resolves and shows the quoted text
- [ ] The deep link loads and shows the finding being fixed
- [ ] The logo `src` returns HTTP 200 and sits in the footer at 200px
- [ ] Score, grade, and pillars appear nowhere above "How I found it"
- [ ] No ask of any kind
- [ ] Read it once as the maintainer: does it read as help or as a pitch?

## Worked example

`giovanisp/everything-claude-code` — three command files spelled the
tool-permission key `allowed_tools`; Claude Code reads `allowed-tools`. Three
characters, one screen of diff, cited to the vendor's frontmatter reference,
confirmable with a single `grep`. The score moved 70.1 → 76.1, and that number
appears nowhere in the PR.
