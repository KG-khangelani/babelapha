# Airflow GitSync Setup

This GitSync container automatically syncs DAGs from the Git repository to your Airflow deployment running in the same Kubernetes cluster.

## Quick Start

### Build the container:
```bash
cd docker/airflow-gitsync
docker build -t airflow-gitsync:latest .
```

### Test sync (from cluster):
```bash
docker run --rm \
  -e GITHUB_REPO_URL=https://github.com/KG-khangelani/babelapha.git \
  -e GITHUB_BRANCH=main \
  -e AIRFLOW_NAMESPACE=airflow \
  -v ~/.kube:/root/.kube:ro \
  --network host \
  airflow-gitsync:latest
```

## TeamCity Setup (Manual UI Configuration)

### Build Steps:

**Step 1: Validate DAG Syntax**

Reference: `docker/airflow-gitsync/validate_dags.sh`

```bash
#!/bin/bash
set -e

echo "==> Installing Airflow for DAG validation"
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install "apache-airflow==2.9.1" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.1/constraints-3.11.txt"

# Install providers used in DAGs
pip install \
  apache-airflow-providers-cncf-kubernetes \
  apache-airflow-providers-amazon

echo "==> Validating DAG syntax"
python - <<'PYEOF'
import sys
import py_compile
from pathlib import Path

dag_folder = Path("pipelines/airflow/dags")
dag_files = list(dag_folder.glob("*.py"))

if not dag_files:
    print("✗ No DAG files found")
    sys.exit(1)

print(f"Found {len(dag_files)} DAG file(s)")
errors = []

for dag_file in dag_files:
    try:
        py_compile.compile(str(dag_file), doraise=True)
        print(f"  ✓ {dag_file.name}")
    except py_compile.PyCompileError as e:
        print(f"  ✗ {dag_file.name}: {e}")
        errors.append((dag_file.name, str(e)))

if errors:
    print("\n✗ Syntax errors detected:")
    for filename, error in errors:
        print(f"  {filename}: {error}")
    sys.exit(1)

print("\n✓ All DAG files passed syntax validation")
PYEOF
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
