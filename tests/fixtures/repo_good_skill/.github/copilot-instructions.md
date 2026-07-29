# Contoso Deploy Tool

## Overview
This repository builds and deploys the Contoso web application to staging and production.

## Tech stack
- Node.js/TypeScript backend, Vite frontend
- Deployed via GitHub Actions to Azure App Service

## Coding guidelines
- Use `date-fns` instead of `moment.js`, because moment.js is deprecated and increases bundle size.
- Prefer async/await over raw Promise chains to avoid unhandled-rejection bugs.
- Keep modules under `src/` focused; split files above 300 lines so that reviews stay tractable.

## Project structure
- `src/` — application source
- `scripts/` — build, deploy, and healthcheck scripts
- `.github/skills/` — reusable agent skills (see deploy-helper)

## Verification
- Run `npm test` and re-run until the tests pass before committing.
- Run `npm run typecheck` and `npm run lint` when you are done, and verify a clean exit.
- Include the test output in your summary as evidence, not just an assertion that it passed.

## Resources
- `scripts/build.sh`, `scripts/deploy.sh`, `scripts/healthcheck.sh`
- MCP: the `github` server in `.mcp.json` provides issue and PR access.
