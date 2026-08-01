# Deploying CodeCompass

CodeCompass ships as a single container: a FastAPI backend (`airx_server`)
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
docker build -t registry.example.com/codecompass:0.3.0 .
docker push registry.example.com/codecompass:0.3.0

helm install codecompass deploy/helm/codecompass \
  --set image.repository=registry.example.com/codecompass \
  --set image.tag=0.3.0
```

The chart deploys 2 replicas (ClusterIP service on port 80 → container 8080),
liveness/readiness probes on `/api/health`, a non-root pod (uid 10001) with a
read-only root filesystem, and a writable `emptyDir` at `/tmp`.

### GitHub token (recommended)

Store the token in a Secret and reference it:

```sh
kubectl create secret generic codecompass-github \
  --from-literal=github-token=ghp_yourtoken

helm upgrade --install codecompass deploy/helm/codecompass \
  --set image.repository=registry.example.com/codecompass \
  --set image.tag=0.3.0 \
  --set github.tokenSecretName=codecompass-github
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
    - host: codecompass.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: codecompass-tls
      hosts:
        - codecompass.example.com
```

```sh
helm upgrade --install codecompass deploy/helm/codecompass -f my-values.yaml
```

### Private repositories (local-repos mode)

Mount an existing PersistentVolumeClaim (or a hostPath) containing repository
clones read-only at `/repos`:

```sh
helm upgrade --install codecompass deploy/helm/codecompass \
  --set localRepos.enabled=true \
  --set localRepos.existingClaim=org-repos-pvc
```

or, for a single-node/dev cluster:

```sh
helm upgrade --install codecompass deploy/helm/codecompass \
  --set localRepos.enabled=true \
  --set localRepos.hostPath=/srv/repos
```

This sets `ALLOW_LOCAL_PATHS=true` and `LOCAL_REPOS_ROOT=/repos` in the
container; analyze with `POST /api/analyze {"path": "<repo-dir-name>"}`.

### Autoscaling

```sh
helm upgrade --install codecompass deploy/helm/codecompass \
  --set autoscaling.enabled=true \
  --set autoscaling.minReplicas=2 \
  --set autoscaling.maxReplicas=5 \
  --set autoscaling.targetCPUUtilizationPercentage=80
```

### Verify

```sh
helm lint deploy/helm/codecompass
kubectl port-forward svc/codecompass 8080:80
curl -s http://localhost:8080/api/health   # {"status":"ok"}
```

## Configuration reference

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | unset | GitHub API token for higher rate limits and private-repo API access |
| `ALLOW_LOCAL_PATHS` | `false` | Enable local-path analysis mode |
| `LOCAL_REPOS_ROOT` | unset | Root directory local paths are confined to |
| `STATIC_DIR` | `/opt/codecompass/static` (image) | Location of the built SPA |
| `MAX_CONCURRENT_ANALYSES` | `4` | Concurrent analysis cap per replica |
