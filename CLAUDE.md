# CLAUDE.md

## Overview

@.github/copilot-instructions.md

The import above bridges the full project overview, tech stack, coding
guidelines, and directory structure from the canonical Copilot entry point.

## Claude Code specifics

- Subagents live under `.claude/agents/`; reusable slash commands live under
  `.claude/commands/` (e.g. `/verify`). Reusable Copilot prompt files live
  under `.github/prompts/`.
- Keep everything else in the bridged file so Copilot and Claude Code read
  one canonical set of instructions instead of two documents drifting apart.
