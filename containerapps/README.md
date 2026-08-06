# Deploying AgentCompass to Azure Container Apps (`containerapps/`)

The public, highly-available hosting path for this repo: one stateless
container (FastAPI + prebuilt React SPA, no database, no persistent state),
so Azure Container Apps (ACA) gets nearly all the HA characteristics an AKS
cluster would (multi-replica, self-healing, autoscaling, managed HTTPS
ingress, revision-based rollback) at a fraction of the cost and with none of
the cluster/ingress/cert-manager maintenance. This supersedes the AKS plan
considered earlier in this session — see `deploy/helm/agentcompass` (Helm)
and `render.yaml` (Render) for the other two supported install paths; only
run one against a given app instance.

- **Subscription:** Visual Studio Enterprise Subscription (`99c945ee-7bba-4387-8206-b3178293cfb0`)
- **Resource group:** `agent-compass-rg` (East US)
- **Live URL:** <https://agentcompass.ashymeadow-b5411f47.eastus.azurecontainerapps.io/> (deployed 2026-08-05)

## Estimated cost

~$20–40/month steady-state: 2 always-on replicas × 0.5 vCPU/1Gi (Consumption
plan, ~$15–25), Log Analytics ingestion for the environment (~$5, low volume),
ACR Basic (~$5). No load balancer, no VNET, no per-node billing — all things
an AKS cluster would add on top of a similar container footprint.

## 1. One-time prerequisites

```sh
az upgrade   # Azure CLI here is 2.40.0; Container Apps needs a recent CLI
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
az account set --subscription 99c945ee-7bba-4387-8206-b3178293cfb0
```

Each `register` call returns immediately while registration finishes in the
background (usually 1-2 minutes) — poll with
`az provider show -n <namespace> --query registrationState -o tsv` until it
reads `Registered` before moving on to the next step.

## 2. Registry + Log Analytics + Container Apps environment

```sh
az acr create \
  --resource-group agent-compass-rg \
  --name agentcompassacr \
  --sku Basic

az monitor log-analytics workspace create \
  --resource-group agent-compass-rg \
  --workspace-name agentcompass-logs

az containerapp env create \
  --resource-group agent-compass-rg \
  --name agentcompass-env \
  --location eastus \
  --logs-workspace-id $(az monitor log-analytics workspace show \
      --resource-group agent-compass-rg --workspace-name agentcompass-logs \
      --query customerId -o tsv) \
  --logs-workspace-key $(az monitor log-analytics workspace get-shared-keys \
      --resource-group agent-compass-rg --workspace-name agentcompass-logs \
      --query primarySharedKey -o tsv)
```

(On Windows PowerShell, resolve the two `$()` substitutions into separate
variables first and pass their values directly — command substitution inside
a multi-line PowerShell block can silently pass an empty string to
`--logs-workspace-key`.)

The environment already spreads replicas across the region's available
infrastructure for you — no explicit AZ configuration needed for the HA
baseline below. (Optional: pin to specific zones with a VNET-integrated,
`--zone-redundant` environment — extra cost/complexity, only worth it for
stricter SLA requirements than this app has today.)

## 3. Build and push the image

```sh
az acr login --name agentcompassacr
docker build -t agentcompassacr.azurecr.io/agentcompass:0.3.0 .
docker push agentcompassacr.azurecr.io/agentcompass:0.3.0
```

## 4. Fill in the manifest and create the app

Edit `containerapps/agentcompass.yaml`: replace `<ACR_NAME>` (both spots) and
`<MANAGED_ENVIRONMENT_ID>` with:

```sh
az containerapp env show -g agent-compass-rg -n agentcompass-env --query id -o tsv
```

```sh
az containerapp create \
  --resource-group agent-compass-rg \
  --name agentcompass \
  --yaml containerapps/agentcompass.yaml
```

Then grant the app's system-assigned identity `AcrPull` on the registry (this
is what lets `registries: [{server: ..., identity: system}]` in the manifest
pull without a password):

```sh
principalId=$(az containerapp show -g agent-compass-rg -n agentcompass \
  --query identity.principalId -o tsv)
acrId=$(az acr show -g agent-compass-rg -n agentcompassacr --query id -o tsv)

az role assignment create --assignee $principalId --role AcrPull --scope $acrId
```

If `containerapp create` ran before this role existed, the first revision may
fail to pull the image and `az containerapp show`'s `properties.provisioningState`
can get stuck on `Failed` (`deploymentErrors: "Operation expired"`) even once
the pod itself recovers. Clear it by re-applying the manifest once the role
assignment is in place:

```sh
az containerapp update -g agent-compass-rg -n agentcompass --yaml containerapps/agentcompass.yaml
```

## 5. Get the public URL

```sh
az containerapp show -g agent-compass-rg -n agentcompass \
  --query properties.configuration.ingress.fqdn -o tsv
```

That's it — the FQDN is already `https://`, backed by a Microsoft-managed
certificate; no cert-manager/nip.io/DNS steps required. Point a custom domain
at it later with `az containerapp hostname add` + `az containerapp ssl upload`
if you get one; nothing else in the manifest changes.

## 6. (Optional) GitHub token

Raises the GitHub API limit from 60 to 5000 req/hour. Set it directly via the
CLI — never commit a real token to `agentcompass.yaml`:

```sh
az containerapp secret set \
  --resource-group agent-compass-rg --name agentcompass \
  --secrets github-token=ghp_yourtoken

az containerapp update \
  --resource-group agent-compass-rg --name agentcompass \
  --set-env-vars GITHUB_TOKEN=secretref:github-token
```

(Then uncomment the matching `secrets:`/`env:` lines in `agentcompass.yaml`
so the source of truth reflects reality — the CLI commands above are what
actually apply it.)

## 7. CI/CD (GitHub Actions → Azure via OIDC)

The `deploy` job in `.github/workflows/ci.yml` builds+pushes an image and runs
`az containerapp update` on every push to `main`, once every other CI job has
passed. It authenticates with `azure/login@v2` via OIDC — no client secret is
stored in GitHub. This was set up with a **user-assigned managed identity**
(UAMI) rather than a classic `az ad sp create-for-rbac` service principal,
because creating a UAMI (`Microsoft.ManagedIdentity/userAssignedIdentities`)
is an ARM resource-group operation, not an Entra app registration — it isn't
blocked by tenants that restrict "Users can register applications".

```sh
# 1. Create the identity
az identity create -g agent-compass-rg -n agentcompass-gha

# 2. Trust GitHub's OIDC tokens for pushes to main on this repo
az identity federated-credential create \
  --identity-name agentcompass-gha --resource-group agent-compass-rg \
  --name gha-production-environment \
  --issuer "https://token.actions.githubusercontent.com" \
  --subject "repo:YoavLax@48318330/agent-compass@1316443332:environment:production" \
  --audiences "api://AzureADTokenExchange"

# 3. Least-privilege RBAC: push images, update the container app — nothing else
principalId=$(az identity show -g agent-compass-rg -n agentcompass-gha --query principalId -o tsv)
acrId=$(az acr show -g agent-compass-rg -n agentcompassacr --query id -o tsv)
rgId=$(az group show -n agent-compass-rg --query id -o tsv)
az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role AcrPush --scope $acrId
az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role "Container Apps Contributor" --scope $rgId
```

The `deploy` job in `ci.yml` sets `environment: production`, so GitHub issues
an **environment-scoped** OIDC subject, not the more commonly documented
`repo:<owner>/<repo>:ref:refs/heads/<branch>` form — and this org has
immutable-ID subject claims enabled, so `<owner>`/`<repo>` above are actually
`<owner>@<owner_id>`/`<repo>@<repo_id>`. Get the exact subject GitHub is
presenting from a failed login's error message (`AADSTS700213: No matching
federated identity record found for presented assertion subject '...'`)
rather than guessing the format — a mismatch here is the most likely reason
`azure/login` fails after everything else is configured correctly.

Then set three repo secrets (an account with admin/write access to the repo
is required — an OAuth token merely holding the `repo` scope is not enough if
the signed-in account itself isn't a collaborator):

```sh
clientId=$(az identity show -g agent-compass-rg -n agentcompass-gha --query clientId -o tsv)
tenantId=$(az identity show -g agent-compass-rg -n agentcompass-gha --query tenantId -o tsv)
gh secret set AZURE_CLIENT_ID -b "$clientId"
gh secret set AZURE_TENANT_ID -b "$tenantId"
gh secret set AZURE_SUBSCRIPTION_ID -b "99c945ee-7bba-4387-8206-b3178293cfb0"
```

If another job/environment needs to deploy too, add another
`federated-credential` with a matching `--subject` rather than widening the
existing one — read the exact subject off a failed run's `AADSTS700213` error
rather than guessing it.

## High availability — what's in place and why

| Concern | Mechanism |
| --- | --- |
| Instance failure | `minReplicas: 2` — never a single point of failure; ACA restarts unhealthy replicas automatically based on the liveness probe |
| Load spikes | HTTP-concurrency scale rule, 2→5 replicas; Consumption plan provisions capacity automatically, no node management |
| Bad rollout | `activeRevisionsMode: Single` still creates a new revision per deploy; `az containerapp revision list` + `az containerapp revision activate <previous>` rolls back instantly |
| Public entry point | Managed ingress + **automatic Microsoft-managed TLS certificate** — no ingress controller or cert renewal to operate |
| Health | Liveness/readiness probes on `/api/health` (same endpoint the Helm chart and Dockerfile `HEALTHCHECK` already use) |

## Maintaining it

- **Deploys:** automatic on push to `main` — the `deploy` job in
  `.github/workflows/ci.yml` builds a `<version>-<sha>` tagged image, pushes
  it to `agentcompassacr`, and runs `az containerapp update --image ...`. To
  deploy by hand instead, bump the tag in `agentcompass.yaml` and re-run
  `az containerapp update -g agent-compass-rg -n agentcompass --yaml containerapps/agentcompass.yaml`.
  Each deploy is a new revision; traffic only shifts once the new revision's
  readiness probe passes.
- **Rollback:** `az containerapp revision list -g agent-compass-rg -n agentcompass -o table`,
  then `az containerapp revision activate --resource-group agent-compass-rg --name agentcompass --revision <name>`.
- **Scaling ceiling:** raise `maxReplicas` in `agentcompass.yaml` if sustained
  load regularly hits 5 replicas.
- **Logs/metrics:** `az containerapp logs show -g agent-compass-rg -n agentcompass --follow`,
  or the Log Analytics workspace (`agentcompass-logs`) in the Azure Portal.
- **Secrets rotation:** re-run the `az containerapp secret set` command from
  step 6 with the new value — takes effect on the next revision without any
  YAML change.
