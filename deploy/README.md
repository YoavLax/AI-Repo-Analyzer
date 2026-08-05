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

## Render: continuous deployment from `main`

[`render.yaml`](../render.yaml) declares the hosted deployment as a Render
Blueprint: a free Docker web service built from this repository's existing
Dockerfile. The service is stateless, so there is no database, disk, or volume
to declare.

The `deploy` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
releases every push to `main`. It runs only after **all** other CI jobs pass —
the full test matrix, the frontend build, the Docker image smoke test, the Helm
lint, the dogfood run, and the action self-test — so a green test matrix alone
cannot ship a broken frontend or an unbuildable image.

`autoDeploy: false` in the blueprint is what makes that gate real. With
Render's own auto-deploy left on, a push would release immediately and the CI
gate would be decorative.

### One-time setup

1. Create the service at <https://dashboard.render.com/select-repo?type=blueprint>,
   pointing it at this repository. Render reads `render.yaml` and creates the
   web service from it. A free account is enough; no payment details are
   required.

2. Add the runtime GitHub token in the service's *Environment* tab:

   ```
   GITHUB_TOKEN = ghp_yourtoken
   ```

   This is a **runtime** secret — the server reads `GITHUB_TOKEN` from its
   environment on every request — so it belongs on Render, not in Actions. For
   public repositories it needs **no scopes at all**; an unscoped token still
   raises the GitHub API limit from 60 to 5,000 requests/hour and can do
   nothing else if it leaks. Without it the API answers `429` as soon as the
   shared unauthenticated budget runs out.

3. Tell CI which service to release, in the GitHub repository's
   *Settings → Secrets and variables → Actions*:

   Both are **repository secrets** (*Secrets* tab, not *Variables*):

   | Name | Where to find it |
   | --- | --- |
   | `RENDER_SERVICE_ID` | the `srv-...` id in the service's dashboard URL |
   | `RENDER_API_KEY` | <https://dashboard.render.com/u/settings#api-keys> |

   Actions masks secret values everywhere they would be printed, so the deploy
   job identifies the service in its output by the name and URL it reads back
   from the API — echoing the id would only ever render as `***`.

### How the deploy is verified

Render keeps serving the previous build until the new one is healthy. Polling
`/api/health` straight after triggering a release would therefore pass against
the release being *replaced* — a deploy that failed to build would look
successful.

So the job uses Render's API rather than a deploy hook: it creates a deploy,
gets back that deploy's id, and polls **that specific deploy** until it reports
`live`, failing loudly on `build_failed`, `update_failed`, `pre_deploy_failed`,
`canceled`, or `deactivated`. Only then does it smoke-test the URL — which it
reads back from the API too, because Render assigns the hostname and appends a
suffix when a name is already taken, so it cannot be derived from the
blueprint.

### The `PORT` contract

Render assigns the port and passes it as `$PORT`. The image honours it:

```dockerfile
ENV PORT=8080
CMD ["sh", "-c", "exec uvicorn airx_server.app:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
```

The default keeps Docker Compose, the Helm chart, and the CI smoke tests
working unchanged, and `exec` keeps uvicorn as PID 1 so `SIGTERM` reaches it
directly instead of the platform waiting out its kill timeout. A container that
ignored `$PORT` would build fine on Render and then never answer, so the smoke
test names this as the first thing to check.

### What a free instance is

| | |
| --- | --- |
| Resources | 0.1 CPU, 512 MB RAM |
| Sleep | after 15 min idle; the next request wakes it in 30-60 s |
| Quota | 750 instance-hours/month |
| Cost | none, and no card on file |

0.1 CPU is the real constraint. Analysis is CPU-bound, so `render.yaml` pins
`MAX_CONCURRENT_ANALYSES=1`: admitting several at once on a tenth of a core
makes each slower without finishing any sooner, and risks the memory ceiling.
Expect a single analysis to take appreciably longer than it does locally.

### Deploying somewhere else instead

Nothing in the application is Render-specific — it is one stateless container
that honours `$PORT` and reads `GITHUB_TOKEN`. Google Cloud Run is the natural
step up if 0.1 CPU or the sleep behaviour becomes a problem: its free tier is
perpetual rather than a trial (2M requests, 180k vCPU-seconds, 360k GiB-seconds
per month) and `gcloud run deploy --source .` uses this same Dockerfile, but it
requires a billing account and the free tier only applies in US regions.
Kubernetes is covered by the Helm chart above.

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
