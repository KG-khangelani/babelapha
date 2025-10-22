# Airflow GitSync Setup

This GitSync container automatically syncs DAGs from the Git repository to your Airflow deployment running in the same Kubernetes cluster.

## Docker Containers

### 1. Validation Container (`Dockerfile.validate`)
Pre-built with Airflow + providers for DAG validation

### 2. GitSync Container (`Dockerfile`)
Lightweight Alpine container for syncing DAGs to Kubernetes

## Quick Start

### Build containers:
```bash
cd docker/airflow-gitsync

# Build validation container
docker build -f Dockerfile.validate -t airflow-dag-validator:latest .

# Build sync container
docker build -t airflow-gitsync:latest .
```

### Test locally:
```bash
# Test validation (from repo root)
docker run --rm -v $(pwd):/workspace airflow-dag-validator:latest

# Test sync (from cluster)
docker run --rm \
  -e GITHUB_REPO_URL=https://github.com/KG-khangelani/babelapha.git \
  -e GITHUB_BRANCH=main \
  -v ~/.kube:/root/.kube:ro \
  --network host \
  airflow-gitsync:latest
```

## TeamCity Setup (Manual UI Configuration)

### Build Steps:

**Step 1: Validate DAG Syntax**
```bash
# Build validator image
docker build -f docker/airflow-gitsync/Dockerfile.validate \
  -t airflow-dag-validator:%build.number% \
  docker/airflow-gitsync/

# Run validation
docker run --rm \
  -v %teamcity.build.checkoutDir%:/workspace \
  airflow-dag-validator:%build.number%
```

**Step 2: Build GitSync Container**
```bash
cd docker/airflow-gitsync
docker build -t airflow-gitsync:%build.number% .
docker tag airflow-gitsync:%build.number% airflow-gitsync:latest
```

**Step 3: Sync DAGs to Airflow**
```bash
docker run --rm \
  -e GITHUB_REPO_URL=%vcsroot.url% \
  -e GITHUB_BRANCH=%teamcity.build.branch% \
  -e BUILD_NUMBER=%build.number% \
  -e BUILD_VCS_NUMBER=%build.vcs.number% \
  -e AIRFLOW_NAMESPACE=airflow \
  -v ~/.kube:/root/.kube:ro \
  --network host \
  airflow-gitsync:%build.number%
```

### VCS Trigger:
- **Branch filter**: `+:refs/heads/main`
- **Trigger rules**: `+:pipelines/airflow/dags/**`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_REPO_URL` | `https://github.com/KG-khangelani/babelapha.git` | Repository URL |
| `GITHUB_BRANCH` | `main` | Branch to clone |
| `GITHUB_TOKEN` | (empty) | GitHub PAT for private repos |
| `AIRFLOW_NAMESPACE` | `airflow` | Kubernetes namespace |
| `AIRFLOW_POD_LABEL` | `component=scheduler` | Scheduler pod label |
| `DAGS_FOLDER` | `/opt/airflow/dags` | DAGs directory in pod |
| `SOURCE_DIR` | `pipelines/airflow/dags` | Source directory in repo |

## Verify Sync

```bash
# Check DAGs in Airflow
kubectl get pods -n airflow -l component=scheduler
kubectl exec -n airflow <scheduler-pod> -- ls -lh /opt/airflow/dags/
kubectl exec -n airflow <scheduler-pod> -- airflow dags list
```

## Troubleshooting

**kubectl access denied**: Verify cluster access with `kubectl get pods -n airflow`

**No DAGs found**: Check that `pipelines/airflow/dags/` contains `.py` files

**DAG not in UI**: Wait 30-60s for Airflow to detect changes, or check scheduler logs:
```bash
kubectl logs -n airflow -l component=scheduler --tail=100
```
