---
name: build-e2e-platform
description: 'Build and run the AgentCompass platform locally (Docker Compose) for end-to-end testing, wiring up GITHUB_TOKEN so live GitHub analyses avoid the 60 req/h anonymous rate limit. Use for "run e2e tests", "spin up the platform locally", "test against docker", "verify live analyze endpoint", "rebuild agentcompass container", "set GITHUB_TOKEN for testing".'
---

# Build the AgentCompass platform locally for e2e testing

## When to use
- Before/after changing `src/airx/**` or `src/airx_server/**` and you need to verify against the real, containerized service (not just `pytest`).
- Running the fixture-based e2e suite (`tests/test_e2e_fixtures.py`) plus a live smoke test against a real GitHub repo.
- Testing GitHub-rate-limit-sensitive code paths (`src/airx/ingest.py`), which need `GITHUB_TOKEN` to get 5000 req/h instead of 60.

## Prerequisites
- Docker Desktop running.
- A GitHub token with at least `public_repo` scope (or default read scope) — do NOT hardcode it in any file. Get it from the environment or the `gh` CLI, never print it.

## Procedure

### 1. Get a GitHub token into the shell session (never write it to disk)
Prefer reusing an already-authenticated `gh` CLI session over asking the user to paste a token:

```powershell
$env:GITHUB_TOKEN = gh auth token
```

If `gh auth token` fails (not logged in), ask the user to run `gh auth login` first, or to set `$env:GITHUB_TOKEN` themselves in the terminal — never request the token value via chat/askQuestions (it's a secret).

### 2. Run the pure-Python e2e/unit suite first (fast, no Docker needed)
```powershell
.venv\Scripts\python.exe -m pytest -q
```
This covers `tests/test_e2e_fixtures.py` (fs.scan → build_index → score pipeline over `tests/fixtures/*`) and everything else. Fix failures here before touching Docker.

### 3. Build and start the local platform
```powershell
docker compose up -d --build
```
This rebuilds the `agentcompass:latest` image (multi-stage: Vite build of `web/` + FastAPI/uvicorn runtime) and (re)creates the container, forwarding `GITHUB_TOKEN` from the current shell env into the container per `docker-compose.yml`.

### 4. Wait for health, then smoke-test the live API
```powershell
Invoke-RestMethod http://localhost:8080/api/health
Invoke-RestMethod http://localhost:8080/api/analyze -Method Post -ContentType application/json -Body '{"source":"owner/repo"}'
```
Swap `owner/repo` for a real public repo. A successful response confirms the container picked up `GITHUB_TOKEN` and the full build→analyze pipeline works end-to-end.

### 5. Private repos (local-path mode)
The default compose service only supports public GitHub URLs via the API. For a private repo, clone it locally and analyze via the CLI against the local venv instead of the container (reflects latest source without rebuilding):
```powershell
gh repo clone owner/private-repo $env:TEMP\e2e-clone -- --depth 1
.venv\Scripts\python.exe -m airx.cli analyze $env:TEMP\e2e-clone
```

### 6. Clean up
```powershell
docker compose down
Remove-Item -Recurse -Force $env:TEMP\e2e-clone -ErrorAction SilentlyContinue
```
Also delete any scratch `*-report.json` files left in the repo root.

## Notes
- `GITHUB_TOKEN` is optional functionally (anonymous calls work) but required to avoid 429s during repeated live testing — see `src/airx/ingest.py` line ~147 and `docker-compose.yml` header comment.
- Other tunable env vars passed through compose: `MAX_FETCH_FILES`, `MAX_FILE_BYTES`, `MAX_TOTAL_BYTES` (all optional, defaults in `src/airx_server/config.py`).
- Never commit a token into `docker-compose.yml`, `.env`, or test fixtures — it's read from the shell environment only (`${GITHUB_TOKEN:-}`).
