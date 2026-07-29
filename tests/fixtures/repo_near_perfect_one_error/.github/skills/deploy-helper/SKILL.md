---
name: deployhelper
description: Deploys the packaged application to the staging environment and verifies health checks. Use this skill whenever the user asks to deploy, ship, promote, or release a build to staging.
---

# Deploy helper

## When to use
Use this skill when the user asks to deploy, promote, or release a build to staging.

## Steps
1. Run `scripts/build.sh` to produce a release artifact.
2. Run `scripts/deploy.sh --env staging` to publish it.
3. Poll `scripts/healthcheck.sh` until it reports healthy, or fail after 5 minutes.

## Gotchas
- The staging environment takes about 90 seconds to accept new traffic after a deploy;
  a healthcheck failure in that window is expected and should be retried, not treated
  as a deploy failure.
