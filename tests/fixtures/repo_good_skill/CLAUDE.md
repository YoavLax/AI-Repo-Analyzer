# Contoso Deploy Tool

## Overview
This repository builds and deploys the Contoso web application to staging and production.

## Tech stack
- Node.js/TypeScript backend, Vite frontend

## Coding guidelines
- Use `date-fns` instead of `moment.js`, because moment.js is deprecated and increases bundle size.
- Prefer async/await over raw Promise chains to avoid unhandled-rejection bugs.

## Project structure
- `src/` — application source; `scripts/` — build and deploy scripts.

## Workflow
- Run `npm test` and re-run until the tests pass before committing; verify a clean exit.
- Run `npm run typecheck` when you are done.
- Show the test output as evidence in your summary.
- Prefer running a single test file over the whole suite for speed.
