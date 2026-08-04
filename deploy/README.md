# Deploying AgentCompass

AgentCompass ships as a single container: a FastAPI backend (`airx_server`)
serving the analyzer API and the built React SPA. Two supported paths:
Docker Compose for a single host, Helm for Kubernetes.

## Quickstart: Docker Compose

From the repository root:

```sh
# Optional but recommended: raises the GitHub API limit from 60 to 5000 req/h.
export GITHUB_TOKEN=ghp_yourtoken

docker compose up --build
```

Open <http://localhost:8080>, paste a public GitHub repository URL (or
`owner/repo`), and get the report. Health endpoint: `GET /api/health`.

### Private repositories (self-hosting, local-path mode)

To analyze repositories that never leave your network, mount clones read-only
into the container and enable local-path mode. In `docker-compose.yml`,
replace the `environment:` block with the commented alternative:

```yaml
    environment:
      GITHUB_TOKEN: ${GITHUB_TOKEN:-}
      ALLOW_LOCAL_PATHS: "true"
      LOCAL_REPOS_ROOT: /repos
    volumes:
      - ./repos:/repos:ro
```

Place clones under `./repos/` and analyze via the UI's local tab or:

```sh
curl -s -X POST http://localhost:8080/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"path": "my-repo"}'
```

Paths are strictly confined to `LOCAL_REPOS_ROOT`; traversal and symlink
escapes are rejected. Local-path mode stays disabled unless
`ALLOW_LOCAL_PATHS` is explicitly set.

## Kubernetes: Helm

Build and push the image to a registry your cluster can pull from, then:

```sh
docker build -t registry.example.com/agentcompass:0.3.0 .
docker push registry.example.com/agentcompass:0.3.0

helm install agentcompass deploy/helm/agentcompass \
  --set image.repository=registry.example.com/agentcompass \
  --set image.tag=0.3.0
```

The chart deploys 2 replicas (ClusterIP service on port 80 → container 8080),
liveness/readiness probes on `/api/health`, a non-root pod (uid 10001) with a
read-only root filesystem, and a writable `emptyDir` at `/tmp`.

### GitHub token (recommended)

Store the token in a Secret and reference it:

```sh
kubectl create secret generic agentcompass-github \
  --from-literal=github-token=ghp_yourtoken

helm upgrade --install agentcompass deploy/helm/agentcompass \
  --set image.repository=registry.example.com/agentcompass \
  --set image.tag=0.3.0 \
  --set github.tokenSecretName=agentcompass-github
```

The key inside the secret defaults to `github-token`
(`github.tokenSecretKey`).

### Ingress with TLS

```yaml
# my-values.yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: agentcompass.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: agentcompass-tls
      hosts:
        - agentcompass.example.com
```

```sh
helm upgrade --install agentcompass deploy/helm/agentcompass -f my-values.yaml
```

### Private repositories (local-repos mode)

Mount an existing PersistentVolumeClaim (or a hostPath) containing repository
clones read-only at `/repos`:

```sh
helm upgrade --install agentcompass deploy/helm/agentcompass \
  --set localRepos.enabled=true \
  --set localRepos.existingClaim=org-repos-pvc
```

or, for a single-node/dev cluster:

```sh
helm upgrade --install agentcompass deploy/helm/agentcompass \
  --set localRepos.enabled=true \
  --set localRepos.hostPath=/srv/repos
```

This sets `ALLOW_LOCAL_PATHS=true` and `LOCAL_REPOS_ROOT=/repos` in the
container; analyze with `POST /api/analyze {"path": "<repo-dir-name>"}`.

### Autoscaling

```sh
helm upgrade --install agentcompass deploy/helm/agentcompass \
  --set autoscaling.enabled=true \
  --set autoscaling.minReplicas=2 \
  --set autoscaling.maxReplicas=5 \
  --set autoscaling.targetCPUUtilizationPercentage=80
```

### Verify

```sh
helm lint deploy/helm/agentcompass
kubectl port-forward svc/agentcompass 8080:80
curl -s http://localhost:8080/api/health   # {"status":"ok"}
```

## Fly.io: continuous deployment from `main`

[`fly.toml`](../fly.toml) configures the hosted deployment: region `fra`,
1 vCPU / 1 GB, scaling to zero (`min_machines_running = 0`) and waking on the
first request, so an idle deployment costs nothing.

**The `app` key in `fly.toml` is the single source of truth for which Fly app
this repository deploys to.** `flyctl` reads it automatically for every command
run from the repository root, and the CI deploy job derives the public URL
(`https://<app>.fly.dev`) from it. Nothing else restates the name — a literal
copy elsewhere drifts, and a drifted copy produces a deploy that "succeeds"
while the smoke test probes a hostname that does not exist.

To point the deployment at a different Fly app, change that one line. Fly app
names are immutable, so switching means creating the new app first:

```sh
flyctl apps create <new-name>
# set app = '<new-name>' in fly.toml, then:
flyctl deploy --remote-only
flyctl secrets set GITHUB_TOKEN=ghp_yourtoken
flyctl apps destroy <old-name>          # only once the new one serves traffic
```

The `deploy` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
releases every push to `main` automatically. It runs only after **all** other
CI jobs pass — the full test matrix, the frontend build, the Docker image
smoke test, the Helm lint, and the dogfood run — so a green test matrix alone
cannot ship a broken frontend or an unbuildable image. After `flyctl deploy`
it re-checks the live release: `/api/health`, the served SPA, and that
`/api/version` reports the version in `pyproject.toml` (which catches a
release that silently kept serving the previous image).

### One-time setup

Run these from the repository root so `flyctl` picks up `fly.toml`.

1. Create a Fly deploy token:

   ```sh
   flyctl tokens create deploy --name github-actions
   ```

   Paste the **whole** value, including the leading `FlyV1 ` and the space
   after it — that prefix is part of the token, not a label.

2. Add it as the repository secret `FLY_API_TOKEN`
   (*Settings → Secrets and variables → Actions → New repository secret*), or:

   ```sh
   gh secret set FLY_API_TOKEN --app actions
   ```

3. Set the GitHub API token on the app itself — it is a **runtime** secret, not
   a build one, so it belongs on Fly rather than in Actions:

   ```sh
   flyctl secrets set GITHUB_TOKEN=ghp_yourtoken
   ```

   For public repositories this token needs **no scopes at all**; an unscoped
   token still raises the GitHub API limit from 60 to 5,000 requests/hour, and
   cannot do anything else if it leaks.

The job declares the `production` GitHub environment, so a required reviewer
can be added there later to gate releases behind manual approval without
touching the workflow.

### Manual release

```sh
flyctl deploy --remote-only          # build on Fly's builders
flyctl logs
flyctl status
```

## Configuration reference

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | unset | GitHub API token for higher rate limits and private-repo API access |
| `ALLOW_LOCAL_PATHS` | `false` | Enable local-path analysis mode |
| `LOCAL_REPOS_ROOT` | unset | Root directory local paths are confined to |
| `STATIC_DIR` | `/opt/agentcompass/static` (image) | Location of the built SPA |
| `MAX_CONCURRENT_ANALYSES` | `4` | Concurrent analysis cap per replica |
| `MAX_FETCH_FILES` | `400` | Online-scan cap on classified AI-artifact files fetched per repository; raise it to analyze larger repos without local-path mode |
| `MAX_FILE_BYTES` | `2097152` (2 MB) | Online-scan per-file size cap, in bytes |
| `MAX_TOTAL_BYTES` | `20971520` (20 MB) | Online-scan total fetch-size cap, in bytes |
