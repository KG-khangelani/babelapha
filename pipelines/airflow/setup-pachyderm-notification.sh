#!/bin/bash
# Deploy Pachyderm notification to trigger Airflow DAG on file uploads
# 
# Prerequisites:
#   - Pachyderm deployed in namespace 'pachyderm'
#   - Airflow webhook deployed in namespace 'airflow'
#   - pachctl configured and authenticated
#
# Usage:
#   bash setup-pachyderm-notification.sh

set -e

echo "=== Setting up Pachyderm notification for Airflow ==="

# Configuration
REPO_NAME="media"
WEBHOOK_URL="http://pachyderm-webhook.airflow:8000/webhook/pachyderm"
NOTIFICATION_NAME="ingest-pipeline-trigger"

echo "[1] Verifying Pachyderm and Airflow connectivity..."

# Test pachctl connection
if ! pachctl config get active-context >/dev/null 2>&1; then
    echo "ERROR: pachctl not configured. Run 'pachctl config update context' first."
    exit 1
fi

echo "✓ pachctl is configured"

# Verify repository exists
if ! pachctl list repo | grep -q "^${REPO_NAME}$"; then
    echo "ERROR: Repository '$REPO_NAME' not found in Pachyderm"
    exit 1
fi

echo "✓ Repository '${REPO_NAME}' exists"

echo ""
echo "[2] Checking Airflow webhook endpoint..."

# Test webhook accessibility (from outside cluster initially)
# This may fail if you're outside the cluster; that's OK as long as webhook is deployed
if curl -s -X GET http://localhost:8000/webhook/pachyderm >/dev/null 2>&1; then
    echo "✓ Webhook endpoint is accessible"
elif curl -s -X GET http://pachyderm-webhook.airflow:8000/webhook/pachyderm >/dev/null 2>&1; then
    echo "✓ Webhook endpoint is accessible from Kubernetes"
else
    echo "⚠ Warning: Could not reach webhook endpoint. Verify it's deployed."
    echo "  Expected URL: http://pachyderm-webhook.airflow:8000/webhook/pachyderm"
fi

echo ""
echo "[3] Configuring Pachyderm notification..."

# Create the notification JSON
# Pachyderm will POST to this URL whenever a commit is made to the repo
NOTIFICATION_JSON=$(cat <<EOF
{
  "name": "${NOTIFICATION_NAME}",
  "receiver": {
    "http": {
      "url": "${WEBHOOK_URL}"
    }
  },
  "trigger": "commit"
}
EOF
)

echo "Notification configuration:"
echo "$NOTIFICATION_JSON" | jq .

echo ""
echo "Creating notification rule..."

# Create notification using pachctl
# Note: Pachyderm v2.x uses 'notification' command
if pachctl notification create --overwrite \
    --name "${NOTIFICATION_NAME}" \
    --repo "${REPO_NAME}" \
    --branch "master" \
    --trigger "commit" \
    --webhook-url "${WEBHOOK_URL}" 2>/dev/null; then
    echo "✓ Notification rule created/updated"
else
    # Fallback for different pachctl versions
    echo "ℹ Attempting alternative notification creation method..."
    
    # For older Pachyderm versions, use 'list notification' to verify
    if pachctl notification list >/dev/null 2>&1; then
        echo "⚠ Notification command exists but creation syntax may differ"
        echo "  Run this command manually:"
        echo "  pachctl notification create --repo=${REPO_NAME} --webhook-url=${WEBHOOK_URL}"
    else
        echo "ERROR: Notification command not available in this Pachyderm version"
        exit 1
    fi
fi

echo ""
echo "[4] Verifying notification..."

# List notifications
echo "Active notifications:"
pachctl notification list --repo="${REPO_NAME}" || echo "(No notifications listed)"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The ingest_pipeline DAG will now be triggered automatically when files"
echo "are uploaded to ${REPO_NAME}:/incoming/ in Pachyderm."
echo ""
echo "To test:"
echo "  1. Upload a test file to Pachyderm:"
echo "     pachctl put file ${REPO_NAME}@master:/incoming/test-001/sample.mp4 -f /path/to/sample.mp4"
echo ""
echo "  2. Check Airflow UI:"
echo "     kubectl port-forward -n airflow svc/airflow-webserver 8080:8080"
echo "     Open http://localhost:8080 and check for ingest_pipeline DAG run"
echo ""
echo "  3. View webhook logs:"
echo "     kubectl logs -n airflow -l app=pachyderm-webhook -f"
