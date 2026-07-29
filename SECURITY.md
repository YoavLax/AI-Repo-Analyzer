# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in AI Readiness Analyzer, please
**do not open a public GitHub issue**. Instead, report it privately using one
of these channels:

1. [GitHub Security Advisories](https://github.com/YoavLax/AI-Repo-Analyzer/security/advisories/new)
   for this repository (preferred).
2. Email **yoavfax@gmail.com** with a description of the issue, steps to
   reproduce, and its potential impact.

You should expect an initial response within 5 business days. We will work
with you to understand and resolve the issue, and will credit you in the
release notes unless you prefer to remain anonymous.

## Scope and threat model

This tool performs **static, offline analysis** of a repository's AI-agent
configuration files. Relevant security properties, and where to look if you
suspect an issue:

- **No network access during analysis.** `airx analyze` never makes outbound
  network calls. If you observe one, that's a bug — please report it.
- **No code execution.** Analysis never executes anything found in the
  scanned repository (scripts, hooks, or otherwise). Rules only read and
  parse text.
- **Path traversal.** File-reference validation resolves paths and rejects
  any reference that escapes the skill's own directory (see
  `skills.references.resolve` in `src/airx/rules/skills.py`, CWE-59). If you
  find a bypass, that's a security bug.
- **Symlinks are never followed** during filesystem discovery
  (`src/airx/fs.py`), to avoid escaping the scanned root.
- **Untrusted input.** The tool is designed to safely analyze arbitrary,
  potentially adversarial repositories (e.g. in CI on external PRs). Malformed
  YAML, oversized files, or malicious file names should produce a diagnostic
  or a clean parse error — never a crash, infinite loop, or resource
  exhaustion. Please report any input that causes otherwise.

## Supported Versions

This project is pre-1.0 and does not yet maintain multiple release branches.
Security fixes are applied to the latest release on the `main` branch.
