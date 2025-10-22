#!/bin/bash
set -euo pipefail

echo '=== Airflow DAG GitSync Container ==='
echo ''

WORKSPACE_DIR=${WORKSPACE_DIR:-/workspace}
AIRFLOW_NAMESPACE=${AIRFLOW_NAMESPACE:-airflow}
AIRFLOW_POD_LABEL=${AIRFLOW_POD_LABEL:-component=scheduler}
DAGS_FOLDER=${DAGS_FOLDER:-/opt/airflow/dags}
SOURCE_DIR=${SOURCE_DIR:-pipelines/airflow/dags}
BUILD_NUMBER=${BUILD_NUMBER:-1}
BUILD_VCS_NUMBER=${BUILD_VCS_NUMBER:-unknown}

# Use in-cluster service account if available
if [ -d "/var/run/secrets/kubernetes.io/serviceaccount" ]; then
    export KUBERNETES_SERVICE_HOST=${KUBERNETES_SERVICE_HOST:-kubernetes.default.svc}
    export KUBERNETES_SERVICE_PORT=${KUBERNETES_SERVICE_PORT:-443}
fi

echo 'Configuration:'
echo "  Workspace: ${WORKSPACE_DIR}"
echo "  Source Directory: ${SOURCE_DIR}"
echo "  Airflow Namespace: ${AIRFLOW_NAMESPACE}"
echo "  DAGs Directory: ${DAGS_FOLDER}"
echo "  Build #${BUILD_NUMBER} (Commit: ${BUILD_VCS_NUMBER})"
echo ''

# Use TeamCity's already-checked-out repository
SOURCE_PATH="${WORKSPACE_DIR}/${SOURCE_DIR}"

if [ ! -d "${SOURCE_PATH}" ]; then
    echo "✗ Error: Source directory '${SOURCE_PATH}' not found"
    echo "  Available files in workspace:"
    ls -la "${WORKSPACE_DIR}" || echo "  Workspace directory not accessible"
    exit 1
fi

echo "✓ Found source directory: ${SOURCE_PATH}"
echo "  Files to sync:"
ls -lh "${SOURCE_PATH}"/*.py 2>/dev/null || echo "  No .py files found"
echo ''

# Find Airflow scheduler pod
echo 'Finding Airflow scheduler pod...'
echo "  Namespace: ${AIRFLOW_NAMESPACE}"
echo "  Label: ${AIRFLOW_POD_LABEL}"

if ! kubectl version --client > /dev/null 2>&1; then
    echo '✗ Error: kubectl not working'
    exit 1
fi

echo "  Checking pods in namespace..."
kubectl get pods -n ${AIRFLOW_NAMESPACE} 2>&1 || {
    echo "✗ Error: Cannot access namespace '${AIRFLOW_NAMESPACE}'"
    echo "  Possible causes:"
    echo "  - Namespace doesn't exist"
    echo "  - Insufficient permissions"
    exit 1
}

SCHEDULER_POD=$(kubectl get pods -n ${AIRFLOW_NAMESPACE} -l ${AIRFLOW_POD_LABEL} -o jsonpath='{.items[0].metadata.name}' 2>&1)

if [ -z "${SCHEDULER_POD}" ]; then
    echo "✗ Error: Could not find Airflow scheduler pod with label '${AIRFLOW_POD_LABEL}'"
    echo "  Available pods:"
    kubectl get pods -n ${AIRFLOW_NAMESPACE} -o custom-columns=NAME:.metadata.name,LABELS:.metadata.labels
    exit 1
fi

echo "✓ Found scheduler pod: ${SCHEDULER_POD}"

# Sync DAG files
echo ''
echo "Syncing DAGs to ${DAGS_FOLDER}..."
DAG_COUNT=0
for dag_file in "${SOURCE_PATH}"/*.py; do
    if [ -f "${dag_file}" ]; then
        DAG_NAME=$(basename "${dag_file}")
        echo "  → Copying ${DAG_NAME}"
        
        # Copy file directly to pod
        kubectl cp "${dag_file}" "${AIRFLOW_NAMESPACE}/${SCHEDULER_POD}:${DAGS_FOLDER}/${DAG_NAME}"
        
        DAG_COUNT=$((DAG_COUNT + 1))
    fi
done

if [ ${DAG_COUNT} -eq 0 ]; then
    echo '✗ Warning: No DAG files found to sync'
    exit 1
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