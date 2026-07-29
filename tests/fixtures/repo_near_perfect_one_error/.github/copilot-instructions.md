# Contoso Deploy Tool

This repository builds and deploys the Contoso web application to staging and production.

## Tech stack
- Node.js/TypeScript backend, Vite frontend
- Deployed via GitHub Actions to Azure App Service

## Coding guidelines
- Use `date-fns` instead of `moment.js`; moment.js is deprecated and increases bundle size.
- Prefer async/await over raw Promise chains.

## Project structure
- `src/` — application source
- `scripts/` — build, deploy, and healthcheck scripts
- `.github/skills/` — reusable agent skills (see deploy-helper)

## Resources
- `scripts/build.sh`, `scripts/deploy.sh`, `scripts/healthcheck.sh`
- Run tests with `npm test` and typecheck with `npm run typecheck` before committing.
