# Contoso Deploy Tool

This repository builds and deploys the Contoso web application to staging and production.

## Tech stack
- Node.js/TypeScript backend, Vite frontend

## Coding guidelines
- Use `date-fns` instead of `moment.js`; moment.js is deprecated and increases bundle size.

## Workflow
- Run `npm test` before committing.
- Prefer running a single test file over the whole suite for speed.
