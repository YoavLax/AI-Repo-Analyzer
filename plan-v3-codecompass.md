# CodeCompass — Web Application Plan (v0.3.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship **CodeCompass** — a production-grade web UI over the airx analyzer: paste a
public GitHub repository URL, get the full AI-readiness report. Clone-free "online scan"
via the GitHub API, no persistence, container-first (Docker Compose + Helm), self-hostable
for private repositories with a local-path mode.

**Architecture:** Three layers, strictly separated. (1) `airx` stays the pure, deterministic
analysis library — zero new dependencies, zero network. (2) A new **ingest** module builds a
`RepoTree` snapshot from the GitHub REST API by listing the full tree and fetching only the
files the rules actually read (~KBs, not the repo). (3) A FastAPI server (`airx_server`)
exposes `POST /api/analyze` and serves the built React SPA. Docker multi-stage image; Helm
chart for Kubernetes.

**Tech stack:** Python 3.11+ / FastAPI / uvicorn / httpx (server extra only) · React 18 +
TypeScript + Vite + Tailwind CSS (frontend) · Docker multi-stage · Helm 3.

**Brand:** CodeCompass — "AI-powered repository understanding". Design language per the
provided references: Untitled-UI-style dashboard — light surfaces, 8-pt spacing, Inter,
rounded-xl cards, subtle borders (#EAECF0), violet primary (#7F56D9) with blue→violet
gradient accents (#2970FF → #7F56D9), full dark-mode variant (slate-950 surfaces). The
compass logo is recreated as an inline SVG (gradient compass rose + two-tone wordmark:
"Code" neutral / "Compass" gradient) with light and dark variants.

---

## 0. Ground rules

1. `airx` (the library) gains **no runtime dependencies and no network access**. The
   determinism contract (plan.md §3) is untouched: ingest happens *before* the pipeline,
   exactly like the CLI's clone path.
2. Documentation in English at every step; tests stay green after every phase.
3. CI must pass on the PR. Known trap from last time: fixture files whose names are
   gitignored by *this* repo (e.g. `.claude/settings.local.json`) silently don't get
   committed — verify with `git ls-files` / `git status --ignored` before pushing.
4. Security is first-class: strict GitHub URL parsing (SSRF-proof — only
   `api.github.com`/`raw.githubusercontent.com` are ever contacted, owner/repo validated
   against `^[A-Za-z0-9_.-]+$`), local-path mode disabled by default and confined to a
   configured root, no shell-outs, size/count caps on every fetch.

## 1. Scope

**In (v0.3.0):**
- `src/airx/ingest.py` — clone-free GitHub snapshot builder (library-side, stdlib-only:
  `urllib.request` with injectable fetcher for tests).
- `src/airx_server/` — FastAPI app: `POST /api/analyze`, `GET /api/health`,
  `GET /api/version`, SPA static serving, env-driven config.
- `web/` — React SPA: hero + URL input, score dashboard (grade ring, platform bars,
  pillar table, findings with severity filters, top-fixes cards, waivers), light/dark.
- `Dockerfile` (multi-stage: node build → python runtime), `docker-compose.yml`,
  `deploy/helm/codecompass/` chart.
- CI: existing Python matrix + `web` job (typecheck + build) + `docker` build job +
  `helm lint` job.
- Docs: README section, `web/README.md`, `deploy/README.md`, CHANGELOG.

**Out:** analysis history/persistence, auth, multi-tenant quotas, GitLab/Bitbucket,
websocket progress streaming (analysis is fast enough to be a single request),
`airx fix`, the GitHub Action.

## 2. The clone-free online scan (`src/airx/ingest.py`)

The insight: the analyzer needs the **full file list** but the **contents of very few
files**. Every rule reads content only from: classified artifacts (discovery patterns),
the four probe files (`package.json`, `Makefile`, `pyproject.toml`, `.gitignore`), and
files inside a skill's directory (scripts/references). Everything else — globs, language
histograms, CI detection, hygiene — needs names only.

```
resolve(owner, repo, ref?) ─┐  GET /repos/{o}/{r}            → default branch (when no ref)
                            ├─ GET /repos/{o}/{r}/git/trees/{ref}?recursive=1
                            │      → full blob list (path, size)   [1 API call]
                            ├─ select_paths(files):
                            │      artifacts  = classify() hits            (patterns.py)
                            │      probe      = the 4 probe file names
                            │      skill dirs = every file under a dir containing SKILL.md
                            ├─ fetch each selected file (raw.githubusercontent.com/{o}/{r}/{sha}/{path})
                            │      caps: ≤ 400 files, ≤ 2 MB/file, ≤ 20 MB total
                            └─ materialize into a temp dir; return
                                   RepoTree(root=temp_dir, files=<full sorted list>)
```

`build_index(tree)` then runs unchanged: content rules see materialized files; name-only
rules see the complete listing. Missing-but-listed non-selected files are exactly the
files no rule reads.

Details:
- `GitHubFetcher` protocol: `get_json(url) -> Any`, `get_raw(url) -> bytes`. Default impl
  uses stdlib `urllib.request` with a 30 s timeout, `User-Agent: codecompass`, and
  `Authorization: Bearer $GITHUB_TOKEN` when the env var is set (60 → 5000 req/h).
  Tests inject a fake fetcher — no network in the test suite, ever.
- API `truncated: true` on the tree (repos > ~100k entries) → `IngestError` with a clear
  message recommending self-hosted local mode (no silent partial analysis).
- Errors map cleanly: 404 → "repository not found or private", 403 with rate-limit
  headers → "GitHub API rate limit exceeded — set GITHUB_TOKEN", network failure →
  "GitHub unreachable". All raised as `IngestError(user_message, status)`.
- Binary-safe: selected files are written as bytes; the parser's existing UTF-8 handling
  does the rest.
- Symlink blobs (git mode `120000`) are dropped from the listing — same semantics as
  `fs.scan`, which never follows symlinks.
- Path safety: every listed path is validated (`no '..' segment, no absolute, no drive
  letter`) before joining; invalid entries are skipped.

Public API:
```python
@dataclass(frozen=True)
class RemoteRepo: owner: str; repo: str; ref: str | None
def parse_github_url(text: str) -> RemoteRepo | None   # url forms + owner/repo shorthand
def fetch_snapshot(remote, workdir, fetcher=None) -> RepoTree
class IngestError(Exception): user_message, status
```

## 3. The server (`src/airx_server/`)

```
src/airx_server/
├── __init__.py
├── app.py        # create_app() factory; routes; SPA mount
├── config.py     # Settings from env: ALLOW_LOCAL_PATHS, LOCAL_REPOS_ROOT,
│                 # GITHUB_TOKEN, STATIC_DIR, MAX_CONCURRENT_ANALYSES (default 4)
└── service.py    # analyze_remote(url, ref) / analyze_local(path) → report dict
```

- `POST /api/analyze` body: `{"source": "<github url | owner/repo>", "ref": null}` or
  `{"path": "<repo-relative path under LOCAL_REPOS_ROOT>"}` (only when
  `ALLOW_LOCAL_PATHS=true`). Response: the canonical `to_json_dict` report plus
  `{"meta": {"source", "ref", "fetched_files", "listed_files", "duration_ms"}}`.
  `duration_ms` lives in `meta`, outside the deterministic report body.
- Errors: 400 invalid input · 404 repo not found/private · 429 GitHub rate limit ·
  413 repo too large · 422 local mode disabled/path outside root. JSON problem bodies:
  `{"error": {"code", "message"}}`.
- Local mode: `path` is resolved strictly under `LOCAL_REPOS_ROOT` (realpath +
  `is_relative_to`; symlink escapes rejected) — the container mounts the org's repos
  read-only at that root.
- Concurrency: an `asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)`; analysis runs in a
  thread executor (the pipeline is CPU-bound and pure).
- No persistence anywhere; each request is self-contained; temp dirs always cleaned.
- Static: serves `web/dist` (path from `STATIC_DIR`) with SPA fallback to `index.html`;
  `/api/*` always wins.
- Packaging: `airx_server` imports FastAPI lazily inside `create_app` so `pip install
  ai-repo-analyzer` (library only) never requires it. New extras:
  `web = ["fastapi>=0.110", "uvicorn[standard]>=0.29"]`, dev extra grows
  `+ fastapi + uvicorn + httpx` (httpx powers Starlette's TestClient).

## 4. Frontend (`web/`)

Vite + React 18 + TypeScript (strict) + Tailwind. No component library — the design
system is hand-rolled to match the reference (Untitled UI direction), which keeps the
bundle lean and the look exact.

```
web/
├── index.html                    # Inter via @fontsource, favicon = compass SVG
├── vite.config.ts                # dev proxy /api → :8000; build → dist/
├── tailwind.config.ts            # tokens: primary violet scale, gradient stops, radii
├── src/
│   ├── main.tsx / App.tsx        # theme provider (class-based dark mode, localStorage)
│   ├── api.ts                    # typed client: AnalyzeRequest/Report DTOs (mirror JSON schema)
│   ├── components/
│   │   ├── Logo.tsx              # inline SVG, light/dark variants, gradient defs
│   │   ├── SearchHero.tsx        # centered logo, URL input + Analyze button, examples,
│   │   │                         #   local-path tab (shown only when /api/version says enabled)
│   │   ├── ScoreRing.tsx         # SVG radial gauge: overall + grade letter, grade color
│   │   ├── PlatformBars.tsx      # copilot vs claude + parity delta chip
│   │   ├── PillarTable.tsx       # per-pillar score/presence/quality bars
│   │   ├── FindingsTable.tsx     # severity chips (error/warn/info), filter tabs, rule id,
│   │   │                         #   path:line, message, expandable why/fix
│   │   ├── TopFixes.tsx          # remediation cards: +gain badge, effort tag, action
│   │   ├── WaiversPanel.tsx      # waived/expired lists (rendered only when non-empty)
│   │   ├── ErrorState.tsx        # per-status friendly errors (404/429/413/422)
│   │   └── ThemeToggle.tsx
│   └── styles.css                # tailwind layers + CSS vars for grade colors
└── README.md
```

- States: idle (hero) → loading (skeleton dashboard + "scanning without cloning" note) →
  report → error. No routing needed; keep it one screen with scroll sections.
- Accessibility: focus rings, aria-labels on gauge/filters, contrast ≥ 4.5 in both themes.
- The report page shows the `meta` line: "N files listed, M fetched — scanned in X ms,
  no clone".

## 5. Containers & deployment

- **Dockerfile** (multi-stage): `node:20-alpine` builds `web/dist` → `python:3.12-slim`
  installs `.[web]`, copies `dist`, runs
  `uvicorn airx_server.app:app --host 0.0.0.0 --port 8080` as non-root user `app` (uid
  10001), `HEALTHCHECK` on `/api/health`.
- **docker-compose.yml**: single `codecompass` service, port `8080:8080`,
  `GITHUB_TOKEN` passthrough; commented-out `volumes:` + `ALLOW_LOCAL_PATHS` block
  showing the private-repos self-host setup (`./repos:/repos:ro`).
- **Helm** `deploy/helm/codecompass/`: Chart.yaml (appVersion 0.3.0), values.yaml
  (image, replicaCount, resources, env incl. `existingSecret` for the token, ingress
  with TLS, `localRepos: {enabled, hostPath|pvc}` for private-repo mode), templates:
  deployment (probes on `/api/health`, securityContext runAsNonRoot/readOnlyRootFilesystem
  + writable `/tmp` emptyDir), service, ingress, serviceaccount, hpa (optional),
  `_helpers.tpl`, NOTES.txt. `helm lint` clean.

## 6. Tests

- `tests/test_ingest.py` — fake fetcher: URL parsing (https, ssh, shorthand, ref,
  rejects non-github hosts), selection logic (artifacts + skill dirs + probe files and
  nothing else), symlink-mode and bad-path entries dropped, caps enforced (413-style
  error), truncated-tree error, rate-limit/404 mapping, and an end-to-end: fake repo →
  snapshot → `score()` equals the same tree analyzed from disk (proves clone-free ≡ clone).
- `tests/test_server.py` — TestClient: analyze happy path (fake fetcher injected via
  app factory), each error status, local mode off→422 / on→confined (traversal + symlink
  escape rejected), health/version, SPA fallback.
- Frontend: `tsc --noEmit` + `vite build` gate in CI (component logic is thin; the typed
  DTOs catch schema drift).
- Full suite green at every phase checkpoint; the 321 existing tests are untouched.

## 7. CI additions (`.github/workflows/ci.yml`)

- Existing matrix job unchanged (server tests skip cleanly when fastapi isn't installed —
  but dev extra now includes it, so they run everywhere).
- `web`: node 20, `npm ci && npm run typecheck && npm run build` in `web/`.
- `docker`: `docker build .` (amd64) — proves the multi-stage image assembles.
- `helm`: `helm lint deploy/helm/codecompass`.
- Dogfood job unchanged + still diffs `docs/RULES.md`.

## 8. Execution phases

- **A (inline):** plan file → `ingest.py` + tests → `airx_server` + tests → pyproject
  extras → suite green.
- **B (workflow, disjoint):** agent 1: entire `web/` frontend; agent 2: Dockerfile +
  compose + Helm + deploy docs; agent 3: README/CHANGELOG/web README. Then inline: CI
  workflow update, local build verification (`npm run build`, `docker build` if the
  daemon is available, `helm lint`).
- **C (workflow):** adversarial review — security (SSRF, path traversal, container
  hardening), ingest correctness vs the clone path, frontend build/typecheck, chart
  validity. Fix confirmed findings; pin with regression tests.
- **D:** commit(s) on `fable5_next`, push, PR to main, watch CI to green
  (`gh run watch`), fix anything red before handing over.

## 9. Acceptance checklist

- [x] `pytest -q` green (361 tests) including ingest + server suites; the 321
      pre-existing tests are intact.
- [x] Fake-fetcher e2e proves snapshot analysis ≡ on-disk analysis for the same tree.
- [x] `npm run typecheck` + `npm run build` clean (168 kB JS / 53 kB gzip, fonts inlined).
- [x] `docker build` + container smoke: `/api/health` ok, `/api/version` reports 0.3.0,
      SPA served with fallback routing, process runs as uid 10001.
- [x] `helm lint` clean; `helm template` renders with every toggle.
- [x] No new deps for the base `airx` install; server deps behind the `web` extra.
- [x] All new files tracked by git (`git status --ignored` audit; only `web/node_modules`
      and `web/dist` ignored, as intended).
- [ ] PR opened; CI fully green on the PR head.

## 10. Phase C adversarial-review outcome

A 22-agent find→verify workflow (5 dimensions: security, ingest correctness, server/API,
frontend, infra/CI) confirmed 10 unique defects (15 findings, 5 duplicates across
dimensions). All are fixed and pinned by regression tests in
`tests/test_review_regressions.py`:

1. **SSRF containment was one-hop only** — `urlopen` follows 3xx to any host and CPython
   forwards `Authorization` across hosts (even https→http), so a GitHub redirect could
   have reached link-local metadata endpoints *and leaked `GITHUB_TOKEN`*. Fixed with a
   redirect handler that re-applies the host allowlist on every hop and strips the token
   off `api.github.com`.
2. **Unbounded response reads** — `read()` buffered a whole body before any size check;
   now capped at read time (per-file 2 MB, API responses 64 MB).
3. **Threadpool starvation (critical)** — a blocking `threading.Semaphore` in a sync
   endpoint parked Starlette's shared 40-thread workers, so a burst of analyses made
   `/api/health` hang and Kubernetes would kill the pod. The endpoint is now `async`,
   awaits an `asyncio.Semaphore`, and runs the CPU-bound pipeline in an executor.
   Verified: health answers in 5 ms while the gate is saturated.
4. **Semaphore bound to one event loop** (introduced by the fix above, caught before
   commit) — gates are now keyed per running loop.
5. **Vendored directories skewed the score** — GitHub lists committed `node_modules/`,
   `dist/`, `__pycache__` entries that `fs.scan` prunes, so a web scan could score
   differently from the CLI on the same commit. Ingest now applies the same exclusions.
6. **`.airx.yml` was ignored server-side** — web analyses skipped the repository's own
   profile/waivers/ignores, so waivers never appeared and scores diverged from
   `airx analyze`. The file is now fetched and applied; a malformed one returns 422.
7. **Read-phase network failures** (reset, timeout, truncated body) escaped the error
   mapping as opaque 500s; they now map to 502 with a user-facing message.
8. **`app` attribute rebuilt the application** on every access, creating independent
   concurrency gates; it is now a cached singleton.
9. **Pydantic validation errors** bypassed the documented `{"error": {code, message}}`
   shape (the SPA mislabeled them); a handler now normalizes them.
10. **`/tree/` URLs and packaging nits** — trailing slashes produced bogus refs (now
    stripped, with a clearer 404 hint for subdirectory URLs); `.dockerignore`'s
    root-anchored `*.egg-info` let `src/*.egg-info` into the image (now `**/*.egg-info`).
