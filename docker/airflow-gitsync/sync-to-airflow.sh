#!/bin/bash
set -euo pipefail

echo '=== Airflow DAG GitSync Container ==='
echo ''

GITHUB_REPO_URL=${GITHUB_REPO_URL:-https://github.com/KG-khangelani/babelapha.git}
GITHUB_BRANCH=${GITHUB_BRANCH:-main}
GITHUB_TOKEN=${GITHUB_TOKEN:-}
AIRFLOW_NAMESPACE=${AIRFLOW_NAMESPACE:-airflow}
AIRFLOW_POD_LABEL=${AIRFLOW_POD_LABEL:-component=scheduler}
DAGS_FOLDER=${DAGS_FOLDER:-/opt/airflow/dags}
SOURCE_DIR=${SOURCE_DIR:-pipelines/airflow/dags}
BUILD_NUMBER=${BUILD_NUMBER:-1}
BUILD_VCS_NUMBER=${BUILD_VCS_NUMBER:-unknown}

echo 'Configuration:'
echo "  GitHub Repo: ${GITHUB_REPO_URL}"
echo "  GitHub Branch: ${GITHUB_BRANCH}"
echo "  Airflow Namespace: ${AIRFLOW_NAMESPACE}"
echo "  DAGs Directory: ${DAGS_FOLDER}"
echo "  Build #${BUILD_NUMBER} (Commit: ${BUILD_VCS_NUMBER})"
echo ''

# Clone the repository
echo 'Cloning repository...'
CLONE_DIR="/tmp/repo"
rm -rf "${CLONE_DIR}"

if [ -n "${GITHUB_TOKEN}" ]; then
    REPO_URL_WITH_TOKEN=$(echo "${GITHUB_REPO_URL}" | sed "s|https://|https://${GITHUB_TOKEN}@|")
    git clone --depth 1 --branch "${GITHUB_BRANCH}" "${REPO_URL_WITH_TOKEN}" "${CLONE_DIR}"
else
    git clone --depth 1 --branch "${GITHUB_BRANCH}" "${GITHUB_REPO_URL}" "${CLONE_DIR}"
fi

cd "${CLONE_DIR}"
echo '✓ Repository cloned'

if [ ! -d "${SOURCE_DIR}" ]; then
    echo "✗ Error: Source directory '${SOURCE_DIR}' not found"
    exit 1
fi

echo "✓ Found source directory: ${SOURCE_DIR}"

# Find Airflow scheduler pod (in-cluster kubectl access)
echo ''
echo 'Finding Airflow scheduler pod...'
SCHEDULER_POD=$(kubectl get pods -n ${AIRFLOW_NAMESPACE} -l ${AIRFLOW_POD_LABEL} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "${SCHEDULER_POD}" ]; then
    echo '✗ Error: Could not find Airflow scheduler pod'
    exit 1
fi

echo "✓ Found scheduler pod: ${SCHEDULER_POD}"

# Sync DAG files
echo ''
echo "Syncing DAGs to ${DAGS_FOLDER}..."
DAG_COUNT=0
for dag_file in "${SOURCE_DIR}"/*.py; do
    if [ -f "${dag_file}" ]; then
        DAG_NAME=$(basename "${dag_file}")
        echo "  → Copying ${DAG_NAME}"
        
        # Copy file directly to pod (in-cluster kubectl access)
        kubectl cp "${dag_file}" "${AIRFLOW_NAMESPACE}/${SCHEDULER_POD}:${DAGS_FOLDER}/${DAG_NAME}"
        
        DAG_COUNT=$((DAG_COUNT + 1))
    fi
done

if [ ${DAG_COUNT} -eq 0 ]; then
    echo '✗ Warning: No DAG files found to sync'
fi

echo ''
echo "✓ Successfully synced ${DAG_COUNT} DAG(s) to Airflow!"
echo ''
echo 'Triggering DAG refresh...'
kubectl exec -n ${AIRFLOW_NAMESPACE} ${SCHEDULER_POD} -- airflow dags list || true

echo ''
echo '✓ Sync complete. Check Airflow UI for new DAGs.'
echo "  Build: #${BUILD_NUMBER}"
echo "  Commit: ${BUILD_VCS_NUMBER}"
