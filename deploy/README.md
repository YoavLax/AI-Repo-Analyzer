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

## Hugging Face Spaces: continuous deployment from `main`

The hosted deployment runs as a Docker Space. The same image the Helm chart and
Docker Compose use is built by the Space itself, so there is no registry to
push to and nothing host-specific in the application.

The `deploy` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
releases every push to `main`. It runs only after **all** other CI jobs pass —
the full test matrix, the frontend build, the Docker image smoke test, the Helm
lint, the dogfood run, and the action self-test — so a green test matrix alone
cannot ship a broken frontend or an unbuildable image. After pushing it polls
the live Space until `/api/health` answers, and fails with the likely cause if
it never does.

### One-time setup

1. Create the Space at <https://huggingface.co/new-space>. A free account is
   enough; no payment details are required.

   | Field | Value |
   | --- | --- |
   | Space name | `agent-compass` |
   | License | MIT |
   | SDK | **Docker** → Blank |
   | Hardware | CPU basic — free |
   | Visibility | **Public** (free Spaces must be public) |

2. Add the runtime GitHub token in the Space's own
   *Settings → Variables and secrets*:

   ```
   GITHUB_TOKEN = ghp_yourtoken
   ```

   This is a **runtime** secret — the server reads `GITHUB_TOKEN` from its
   environment on every request — so it belongs on the Space, not in Actions.
   For public repositories it needs **no scopes at all**; an unscoped token
   still raises the GitHub API limit from 60 to 5,000 requests/hour and can do
   nothing else if it leaks. Without it the API answers `429` as soon as the
   shared unauthenticated budget runs out.

3. Tell CI where to deploy, in the GitHub repository's
   *Settings → Secrets and variables → Actions*:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Variable | `HF_SPACE` | `<owner>/agent-compass` |
   | Secret | `HF_TOKEN` | a **write**-scoped token from <https://huggingface.co/settings/tokens> |

   `HF_SPACE` is a variable rather than a secret on purpose: it is not
   sensitive, and keeping it readable means a failed deploy can say which
   Space it tried to reach.

### How the Space README is produced

A Space takes its configuration from YAML frontmatter in its `README.md`.
Putting that frontmatter in this repository's README would render as noise at
the top of the GitHub project page, so it lives in
[`deploy/huggingface/space-header.md`](huggingface/space-header.md) and is
prepended to a copy of the README only for the artifact pushed to the Space.

`app_port: 8080` in that header is load-bearing: Spaces default to port 7860,
the container listens on 8080, and a mismatch produces a Space that builds
successfully and then never answers. The deploy job asserts it is present
rather than trusting it.

The Space repository is a build artifact, never a source of truth — each
release force-pushes over its history. Edit this repository and let CI
redeploy; changes made in the Space UI are overwritten by the next push.

### Manual release

```sh
pip install -U "huggingface_hub[cli]"
hf auth login                       # paste a write token

cat deploy/huggingface/space-header.md README.md > /tmp/README.space.md
git checkout -b space-build
cp /tmp/README.space.md README.md
git commit -am "space build"
git push --force https://huggingface.co/spaces/<owner>/agent-compass space-build:main
git checkout - && git branch -D space-build
```

### What a free Space does

| | |
| --- | --- |
| Hardware | 2 vCPU, 16 GB RAM, 50 GB disk |
| Sleep | after 48 h idle; the next request wakes it in ~30 s |
| URL | `https://<owner>-agent-compass.hf.space` |
| Cost | none, and no card on file |

### Deploying somewhere else instead

Nothing in the application is Space-specific: it is a single stateless
container that reads `GITHUB_TOKEN`, `PORT`-equivalent settings, and serves
both the API and the SPA. Google Cloud Run is the natural next step if the
Space's sleep behaviour becomes a problem — its free tier is perpetual rather
than a trial, and `gcloud run deploy --source .` uses the same Dockerfile —
but it requires a billing account. Kubernetes is covered by the Helm chart
above.

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
