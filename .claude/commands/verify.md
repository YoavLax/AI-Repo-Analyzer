---
description: Rebuild the Docker platform and run the full verify loop (pytest, frontend typecheck/build, live health check) before calling a change done.
allowed-tools: ["Bash"]
---

Run the AgentCompass verify loop end to end and report the results:

1. `.venv\Scripts\python.exe -m pytest -q` (or `pytest -q` if the venv is
   already active) — full backend test suite. Fix failures before continuing.
2. `cd web && npm run build` — frontend typecheck (`tsc --noEmit`) + Vite
   build gate. Fix failures before continuing.
3. `docker compose up -d --build` — rebuild the `agentcompass:latest` image
   and recreate the container.
4. `Invoke-RestMethod http://localhost:8080/api/health` — confirm the
   container is up, then optionally
   `Invoke-RestMethod http://localhost:8080/api/analyze -Method Post -ContentType application/json -Body '{"source":"owner/repo"}'`
   to smoke-test against a real repo.

Show the output of each step as evidence. Do not report the task as done
until steps 1-2 pass and step 4's health check succeeds.
