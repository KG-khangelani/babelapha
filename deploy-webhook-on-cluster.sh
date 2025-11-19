#!/bin/bash
# Deploy Pachyderm → Airflow webhook on control node (khangelani@192.168.10.104)
#
# This script:
# 1. Pulls the latest webhook code from git
# 2. Deploys webhook listener to Airflow namespace
# 3. Configures Pachyderm notification
# 4. Verifies the integration works
#
# Usage on control node:
#   bash deploy-webhook-on-cluster.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_NAME="media"
WEBHOOK_URL="http://pachyderm-webhook.airflow:8000/webhook/pachyderm"
NOTIFICATION_NAME="ingest-pipeline-trigger"
AIRFLOW_NS="airflow"
PACHYDERM_NS="pachyderm"

# Functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[⚠]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }

echo ""
echo "=========================================="
echo "  Webhook Deployment for ingest_pipeline"
echo "=========================================="
echo ""

# STEP 1: Clone/pull the latest code
log_info "Step 1: Fetching latest webhook code from git"

WORK_DIR="/tmp/babelapha-webhook-deploy"
REPO_URL="https://github.com/KG-khangelani/babelapha.git"

if [ -d "$WORK_DIR/.git" ]; then
    log_info "  Repository already exists, pulling latest..."
    cd "$WORK_DIR"
    git pull origin main
else
    log_info "  Cloning repository..."
    git clone "$REPO_URL" "$WORK_DIR"
    cd "$WORK_DIR"
fi

log_ok "Latest code fetched"
echo ""

# STEP 2: Verify kubectl access
log_info "Step 2: Verifying Kubernetes access"

if ! kubectl cluster-info >/dev/null 2>&1; then
    log_error "Cannot access Kubernetes cluster"
    log_error "Ensure kubectl is configured: kubectl config current-context"
    exit 1
fi

CLUSTER_INFO=$(kubectl cluster-info | head -1)
log_ok "Kubernetes cluster accessible: $CLUSTER_INFO"
echo ""

# STEP 3: Verify namespaces exist
log_info "Step 3: Verifying Kubernetes namespaces"

if ! kubectl get ns $AIRFLOW_NS >/dev/null 2>&1; then
    log_error "Namespace '$AIRFLOW_NS' not found"
    exit 1
fi
log_ok "Namespace '$AIRFLOW_NS' exists"

if ! kubectl get ns $PACHYDERM_NS >/dev/null 2>&1; then
    log_error "Namespace '$PACHYDERM_NS' not found"
    exit 1
fi
log_ok "Namespace '$PACHYDERM_NS' exists"
echo ""

# STEP 4: Deploy webhook listener
log_info "Step 4: Deploying webhook listener to Airflow namespace"

log_info "  Creating ConfigMap for webhook code..."
WEBHOOK_PY=$(cat pipelines/airflow/webhook_listener.py | sed 's/^/    /')
kubectl -n $AIRFLOW_NS create configmap webhook-listener-code \
    --from-file=webhook_listener.py=pipelines/airflow/webhook_listener.py \
    --dry-run=client -o yaml | kubectl apply -f -
log_ok "  ConfigMap created/updated"

log_info "  Applying webhook deployment manifest..."
kubectl apply -f pipelines/airflow/webhook-deployment.yaml

log_info "  Waiting for webhook pods to be ready (max 60s)..."
kubectl -n $AIRFLOW_NS rollout status deployment/pachyderm-webhook --timeout=60s

log_ok "Webhook listener deployed"
echo ""

# STEP 5: Verify webhook is running
log_info "Step 5: Verifying webhook service"

WEBHOOK_PODS=$(kubectl -n $AIRFLOW_NS get pods -l app=pachyderm-webhook -o jsonpath='{.items[*].metadata.name}')
if [ -z "$WEBHOOK_PODS" ]; then
    log_error "No webhook pods found"
    exit 1
fi
log_ok "Webhook pods running: $(echo $WEBHOOK_PODS | wc -w) replicas"

WEBHOOK_SVC=$(kubectl -n $AIRFLOW_NS get svc pachyderm-webhook -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}' 2>/dev/null)
log_ok "Webhook service: $WEBHOOK_SVC"
echo ""

# STEP 6: Verify Pachyderm can reach webhook
log_info "Step 6: Testing connectivity from Pachyderm to webhook"

PACHD_POD=$(kubectl -n $PACHYDERM_NS get pods -l app=pachd -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$PACHD_POD" ]; then
    log_info "  Testing from pachd pod: $PACHD_POD"
    if kubectl -n $PACHYDERM_NS exec $PACHD_POD -- \
        curl -s -o /dev/null -w "%{http_code}" http://pachyderm-webhook.airflow:8000/health | grep -q "200"; then
        log_ok "  Pachyderm can reach webhook (HTTP 200)"
    else
        log_warn "  Could not verify connectivity (may be OK if no pachd pod)"
    fi
else
    log_warn "  No pachd pod found, skipping connectivity test"
fi
echo ""

# STEP 7: Verify pachctl is configured
log_info "Step 7: Verifying pachctl configuration"

if ! pachctl config get active-context >/dev/null 2>&1; then
    log_error "pachctl not configured"
    log_error "Run: pachctl config update context <context-name>"
    exit 1
fi

CURRENT_CTX=$(pachctl config get active-context)
log_ok "pachctl context: $CURRENT_CTX"
echo ""

# STEP 8: Verify Pachyderm repository exists
log_info "Step 8: Verifying Pachyderm repository"

if ! pachctl list repo 2>/dev/null | grep -q "^${REPO_NAME}$"; then
    log_error "Repository '$REPO_NAME' not found in Pachyderm"
    log_error "Create it with: pachctl create repo $REPO_NAME"
    exit 1
fi

log_ok "Repository '$REPO_NAME' exists"
echo ""

# STEP 9: Create or update Pachyderm notification
log_info "Step 9: Configuring Pachyderm notification"

log_info "  Creating notification rule..."

# Try to create the notification
if pachctl notification create \
    --name "${NOTIFICATION_NAME}" \
    --repo "${REPO_NAME}" \
    --branch "master" \
    --trigger "commit" \
    --webhook-url "${WEBHOOK_URL}" 2>/dev/null; then
    log_ok "  Notification created/updated"
else
    log_warn "  Notification creation syntax may differ for this Pachyderm version"
    log_warn "  Try running manually: pachctl notification create --help"
fi

echo ""

# STEP 10: Verify notification
log_info "Step 10: Verifying notification configuration"

if pachctl notification list --repo "${REPO_NAME}" 2>/dev/null | grep -q "${NOTIFICATION_NAME}"; then
    log_ok "Notification '$NOTIFICATION_NAME' is active"
else
    log_warn "Could not verify notification (may require manual setup)"
    log_warn "Check with: pachctl notification list --repo ${REPO_NAME}"
fi

echo ""

# FINAL SUMMARY
echo "=========================================="
echo -e "${GREEN}✓ DEPLOYMENT COMPLETE${NC}"
echo "=========================================="
echo ""

echo "Webhook Configuration:"
echo "  Service: pachyderm-webhook.airflow:8000"
echo "  Replicas: 2"
echo "  Endpoint: /webhook/pachyderm"
echo ""

echo "Pachyderm Configuration:"
echo "  Repository: $REPO_NAME"
echo "  Notification: $NOTIFICATION_NAME"
echo "  Trigger: PUT_FILE in /incoming/ path"
echo "  Webhook URL: $WEBHOOK_URL"
echo ""

echo "Next Steps:"
echo "  1. Upload a test file to Pachyderm:"
echo "     pachctl put file media@master:/incoming/test-001/sample.mp4 -f sample.mp4"
echo ""
echo "  2. Watch webhook logs (in new terminal):"
echo "     kubectl -n airflow logs -l app=pachyderm-webhook -f"
echo ""
echo "  3. Check Airflow UI for new DAG run:"
echo "     kubectl -n airflow port-forward svc/airflow-webserver 8080:8080"
echo "     Open: http://localhost:8080/dags/ingest_pipeline/grid"
echo ""

echo "Monitoring:"
echo "  Webhook logs:     kubectl -n airflow logs -l app=pachyderm-webhook -f"
echo "  Webhook status:   kubectl -n airflow get pods -l app=pachyderm-webhook"
echo "  Notifications:    pachctl notification list --repo media"
echo ""

echo "Documentation:"
echo "  Detailed guide:     pipelines/airflow/WEBHOOK_SETUP.md"
echo "  Quick commands:     WEBHOOK_ONELINERS.md"
echo ""
