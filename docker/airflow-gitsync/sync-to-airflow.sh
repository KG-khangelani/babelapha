#!/bin/bash
set -euo pipefail

echo '=== Airflow DAG GitSync Container ==='
echo ''

WORKSPACE_DIR=${WORKSPACE_DIR:-/workspace}
AIRFLOW_NAMESPACE=${AIRFLOW_NAMESPACE:-airflow}
# Try common label selectors; can be overridden by AIRFLOW_POD_LABEL
AIRFLOW_POD_LABEL=${AIRFLOW_POD_LABEL:-}
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
if [ -n "${AIRFLOW_POD_LABEL}" ]; then
    echo "  Label (explicit): ${AIRFLOW_POD_LABEL}"
fi

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

SELECTORS=()
if [ -n "${AIRFLOW_POD_LABEL}" ]; then
    SELECTORS+=("${AIRFLOW_POD_LABEL}")
fi
SELECTORS+=(
    "component=scheduler"
    "app.kubernetes.io/component=scheduler"
    "airflow-role=scheduler"
    "role=scheduler"
)

SCHEDULER_POD=""
for sel in "${SELECTORS[@]}"; do
    echo "  Trying label selector: ${sel}"
    name=$(kubectl get pods -n ${AIRFLOW_NAMESPACE} -l ${sel} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [ -n "${name}" ]; then
        SCHEDULER_POD=${name}
        AIRFLOW_POD_LABEL=${sel}
        break
    fi
done

if [ -z "${SCHEDULER_POD}" ]; then
    echo "✗ Error: Could not find Airflow scheduler pod using known selectors"
    echo "  Available pods:"
    kubectl get pods -n ${AIRFLOW_NAMESPACE} -o custom-columns=NAME:.metadata.name,LABELS:.metadata.labels
    exit 1
fi

echo "✓ Selected scheduler pod: ${SCHEDULER_POD}"

# Determine if we can copy directly to a running scheduler container
PHASE=$(kubectl get pod -n ${AIRFLOW_NAMESPACE} ${SCHEDULER_POD} -o jsonpath='{.status.phase}' 2>/dev/null || true)
COPY_TARGET_MODE="pod"
COPY_POD_NAME="${SCHEDULER_POD}"

if [ "${PHASE}" != "Running" ]; then
    echo "⚠ Scheduler pod phase is '${PHASE}'. Falling back to syncing via a temporary pod mounting the DAGs PVC."
    # Autodetect DAGs PVC (override with AIRFLOW_DAGS_PVC if set)
    if [ -z "${AIRFLOW_DAGS_PVC:-}" ]; then
        AIRFLOW_DAGS_PVC=$(kubectl get pvc -n ${AIRFLOW_NAMESPACE} -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | grep -E '^airflow-dags$|dags' | head -n1)
    fi
    if [ -z "${AIRFLOW_DAGS_PVC:-}" ]; then
        echo "✗ Error: Could not determine DAGs PVC name. Set AIRFLOW_DAGS_PVC."
        exit 1
    fi
    echo "  Using DAGs PVC: ${AIRFLOW_DAGS_PVC}"

    SYNC_POD="airflow-dags-sync-$(date +%s)"
    cat <<EOF | kubectl apply -n ${AIRFLOW_NAMESPACE} -f -
apiVersion: v1
kind: Pod
metadata:
    name: ${SYNC_POD}
    labels:
        app: airflow-dags-sync
spec:
    restartPolicy: Never
    containers:
    - name: sync
        image: alpine:3.19
        command: ['sh','-c','sleep 600']
        volumeMounts:
        - name: dags
            mountPath: ${DAGS_FOLDER}
    volumes:
    - name: dags
        persistentVolumeClaim:
            claimName: ${AIRFLOW_DAGS_PVC}
EOF

    echo "  Waiting for sync pod to be ready..."
    kubectl wait --for=condition=Ready -n ${AIRFLOW_NAMESPACE} pod/${SYNC_POD} --timeout=60s || {
        echo "✗ Sync pod did not become ready"
        kubectl logs -n ${AIRFLOW_NAMESPACE} ${SYNC_POD} || true
        exit 1
    }
    COPY_TARGET_MODE="sync-pod"
    COPY_POD_NAME="${SYNC_POD}"
fi

# Sync DAG files
echo ''
echo "Syncing DAGs to ${DAGS_FOLDER} (mode: ${COPY_TARGET_MODE})..."
DAG_COUNT=0
for dag_file in "${SOURCE_PATH}"/*.py; do
    if [ -f "${dag_file}" ]; then
        DAG_NAME=$(basename "${dag_file}")
        echo "  → Copying ${DAG_NAME}"
        kubectl exec -n ${AIRFLOW_NAMESPACE} ${COPY_POD_NAME} -- mkdir -p ${DAGS_FOLDER} || true
        kubectl cp "${dag_file}" "${AIRFLOW_NAMESPACE}/${COPY_POD_NAME}:${DAGS_FOLDER}/${DAG_NAME}"
        DAG_COUNT=$((DAG_COUNT + 1))
    fi
done

if [ ${DAG_COUNT} -eq 0 ]; then
    echo '✗ Warning: No DAG files found to sync'
    # Cleanup temp pod if created
    if [ "${COPY_TARGET_MODE}" = "sync-pod" ]; then
        kubectl delete pod -n ${AIRFLOW_NAMESPACE} ${COPY_POD_NAME} --wait=false || true
    fi
    exit 1
fi

if [ "${COPY_TARGET_MODE}" = "sync-pod" ]; then
    echo "  Cleaning up sync pod..."
    kubectl delete pod -n ${AIRFLOW_NAMESPACE} ${COPY_POD_NAME} --wait=false || true
fi

echo ''
echo "✓ Successfully synced ${DAG_COUNT} DAG(s) to Airflow!"
echo ''
echo 'Triggering DAG refresh (if scheduler is running)...'
if [ "${PHASE}" = "Running" ]; then
    kubectl exec -n ${AIRFLOW_NAMESPACE} ${SCHEDULER_POD} -- airflow dags list || true
else
    echo "  Scheduler not running; will be picked up when it starts."
fi

echo ''
echo '✓ Sync complete. Check Airflow UI for new DAGs when scheduler is healthy.'
echo "  Build: #${BUILD_NUMBER}"
echo "  Commit: ${BUILD_VCS_NUMBER}"

# I'm enjoying this, yandibasel