# CodeCompass web frontend

The single-page React UI for CodeCompass: paste a public GitHub repository URL
(or `owner/repo`), get the full AI-readiness report — score ring, pillar
breakdown, findings, top fixes, and waivers. Light and dark themes, no external
requests at runtime (Inter is self-hosted via `@fontsource-variable/inter`).

## Stack

- Vite + React 18 + TypeScript (strict)
- Tailwind CSS (class-strategy dark mode, Untitled-UI-style tokens)
- No component or chart libraries — everything is hand-rolled, including the
  SVG score gauge and the compass logo.

## Development

Run the API server and the Vite dev server side by side:

```bash
# terminal 1 — API on :8000 (from the repo root)
pip install -e ".[dev]"
uvicorn airx_server.app:app --reload --port 8000

# terminal 2 — SPA on :5173
cd web
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies every `/api/*` request to
`http://localhost:8000` (see `vite.config.ts`), so the SPA and the API behave
as a single origin exactly like production — no CORS setup needed.

## Scripts

| Command             | What it does                                    |
| ------------------- | ----------------------------------------------- |
| `npm run dev`       | Vite dev server on :5173 with `/api` proxy      |
| `npm run typecheck` | `tsc --noEmit` (strict; also the CI gate)       |
| `npm run build`     | typecheck + production build into `web/dist/`   |
| `npm run preview`   | serve the production build locally              |

## Production build

```bash
npm run build       # emits web/dist/
```

In production the FastAPI server serves `web/dist/` itself: point `STATIC_DIR`
at it and the server mounts `/assets` and falls back to `index.html` for SPA
routes, while `/api/*` always wins. The Docker image does this automatically.

## How the API types stay honest

`src/api.ts` mirrors the canonical report JSON from
`src/airx/report/json.py::to_json_dict` plus the `meta` block added by
`airx_server/service.py`. If the backend schema changes, updating these DTOs
(and letting `npm run typecheck` fail until every usage is fixed) is the
frontend's schema-drift gate.

## Local-path mode

The hero shows a "GitHub URL | Local path" switch only when
`GET /api/version` reports `local_mode: true` (server started with
`ALLOW_LOCAL_PATHS=true` and a `LOCAL_REPOS_ROOT`). The path field takes a
path relative to that root.
