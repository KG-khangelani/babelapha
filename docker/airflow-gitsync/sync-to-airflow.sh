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

# Use in-cluster service account if available
if [ -d "/var/run/secrets/kubernetes.io/serviceaccount" ]; then
    export KUBERNETES_SERVICE_HOST=${KUBERNETES_SERVICE_HOST:-kubernetes.default.svc}
    export KUBERNETES_SERVICE_PORT=${KUBERNETES_SERVICE_PORT:-443}
fi

echo 'Configuration:'
echo "  GitHub Repo: ${GITHUB_REPO_URL}"
echo "  GitHub Branch: ${GITHUB_BRANCH}"
echo "  Airflow Namespace: ${AIRFLOW_NAMESPACE}"
echo "  DAGs Directory: ${DAGS_FOLDER}"
echo "  Build #${BUILD_NUMBER} (Commit: ${BUILD_VCS_NUMBER})"
echo ''

# Clone the repository with retry logic
echo 'Cloning repository...'
CLONE_DIR="/tmp/repo"
rm -rf "${CLONE_DIR}"

# Configure git for better network handling
# See: https://stackoverflow.com/questions/58372156/how-can-i-resolve-recv-failure-connection-reset-by-peer-error
git config --global http.postBuffer 524288000
git config --global http.lowSpeedLimit 0
git config --global http.lowSpeedTime 999999
git config --global pack.windowMemory 256m
git config --global pack.packSizeLimit 256m

CLONE_ATTEMPTS=3
CLONE_RETRY=0

if [ -n "${GITHUB_TOKEN}" ]; then
    REPO_URL_WITH_TOKEN=$(echo "${GITHUB_REPO_URL}" | sed "s|https://|https://${GITHUB_TOKEN}@|")
    GIT_URL="${REPO_URL_WITH_TOKEN}"
else
    GIT_URL="${GITHUB_REPO_URL}"
fi

# Temporarily disable exit on error for retry loop
set +e

while [ ${CLONE_RETRY} -lt ${CLONE_ATTEMPTS} ]; do
    CLONE_RETRY=$((CLONE_RETRY + 1))
    echo "Attempt ${CLONE_RETRY}/${CLONE_ATTEMPTS} (git clone)..."
    
    # Use minimal clone options to reduce data transfer
    if GIT_CURL_VERBOSE=0 GIT_TRACE=0 git clone \
        --depth 1 \
        --single-branch \
        --branch "${GITHUB_BRANCH}" \
        --no-tags \
        "${GIT_URL}" \
        "${CLONE_DIR}"; then
        echo '✓ Repository cloned via git'
        set -e  # Re-enable exit on error
        break
    else
        if [ ${CLONE_RETRY} -lt ${CLONE_ATTEMPTS} ]; then
            echo "⚠ Git clone failed, retrying in 5 seconds..."
            sleep 5
            rm -rf "${CLONE_DIR}"
        else
            # Fallback: try downloading as tarball
            echo "⚠ Git clone failed all attempts, trying tarball download..."
            REPO_NAME=$(echo "${GITHUB_REPO_URL}" | sed 's|.git$||' | sed 's|https://github.com/||')
            TARBALL_URL="https://github.com/${REPO_NAME}/archive/refs/heads/${GITHUB_BRANCH}.tar.gz"
            
            mkdir -p "${CLONE_DIR}"
            if [ -n "${GITHUB_TOKEN}" ]; then
                curl -L -H "Authorization: token ${GITHUB_TOKEN}" "${TARBALL_URL}" | tar -xz -C "${CLONE_DIR}" --strip-components=1
            else
                curl -L "${TARBALL_URL}" | tar -xz -C "${CLONE_DIR}" --strip-components=1
            fi
            
            if [ $? -eq 0 ]; then
                echo '✓ Repository downloaded via tarball'
                set -e
                break
            else
                echo "✗ Error: Both git clone and tarball download failed"
                echo '  Possible causes:'
                echo '  - Network timeout or MTU issues'
                echo '  - Proxy or firewall blocking HTTPS'
                echo '  - GitHub rate limiting or authentication issues'
                set -e
                exit 1
            fi
        fi
    fi
done

cd "${CLONE_DIR}"

if [ ! -d "${SOURCE_DIR}" ]; then
    echo "✗ Error: Source directory '${SOURCE_DIR}' not found"
    exit 1
fi

echo "✓ Found source directory: ${SOURCE_DIR}"

# Find Airflow scheduler pod (in-cluster kubectl access)
echo ''
echo 'Finding Airflow scheduler pod...'
echo "  Namespace: ${AIRFLOW_NAMESPACE}"
echo "  Label: ${AIRFLOW_POD_LABEL}"

# Debug: Check if kubectl works
if ! kubectl version --client > /dev/null 2>&1; then
    echo '✗ Error: kubectl not working'
    exit 1
fi

# Debug: List all pods in namespace
echo "  Checking pods in namespace..."
kubectl get pods -n ${AIRFLOW_NAMESPACE} 2>&1 || {
    echo "✗ Error: Cannot access namespace '${AIRFLOW_NAMESPACE}'"
    echo "  Possible causes:"
    echo "  - Namespace doesn't exist"
    echo "  - No kubeconfig mounted"
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
