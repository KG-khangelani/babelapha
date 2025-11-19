#!/bin/bash
# Quick deployment guide for webhook on control node
# To be used with khancreate_infra repository
#
# Location: ~/khancreate_infra/
# Control Node: khangelani@192.168.10.104

set -e

echo "=========================================="
echo "Webhook Deployment Quick Guide"
echo "=========================================="
echo ""
echo "This guide uses khancreate_infra for deployment"
echo "Source code is in babelapha repository (GitHub)"
echo ""

# Step 1: Get files from babelapha
echo "Step 1: Download webhook files from babelapha"
echo ""
echo "Option A: From GitHub (recommended)"
echo "  cd ~/khancreate_infra"
echo "  wget https://raw.githubusercontent.com/KG-khangelani/babelapha/main/pipelines/airflow/webhook_listener.py"
echo "  wget https://raw.githubusercontent.com/KG-khangelani/babelapha/main/pipelines/airflow/webhook-deployment.yaml"
echo ""
echo "Option B: From local babelapha if cloned"
echo "  cp ~/babelapha/pipelines/airflow/webhook_listener.py ~/khancreate_infra/"
echo "  cp ~/babelapha/pipelines/airflow/webhook-deployment.yaml ~/khancreate_infra/"
echo ""

# Step 2: Deploy webhook
echo "Step 2: Deploy webhook to Kubernetes"
echo ""
echo "  cd ~/khancreate_infra"
echo "  kubectl -n airflow create configmap webhook-listener-code \\"
echo "    --from-file=webhook_listener.py=webhook_listener.py \\"
echo "    --dry-run=client -o yaml | kubectl apply -f -"
echo ""
echo "  kubectl apply -f webhook-deployment.yaml"
echo ""
echo "  # Wait for pods"
echo "  kubectl -n airflow rollout status deployment/pachyderm-webhook --timeout=60s"
echo ""

# Step 3: Configure Pachyderm
echo "Step 3: Configure Pachyderm notification"
echo ""
echo "  pachctl notification create \\"
echo "    --name ingest-pipeline-trigger \\"
echo "    --repo media \\"
echo "    --branch master \\"
echo "    --trigger commit \\"
echo "    --webhook-url http://pachyderm-webhook.airflow:8000/webhook/pachyderm"
echo ""
echo "  # Verify"
echo "  pachctl notification list --repo media"
echo ""

# Step 4: Test
echo "Step 4: Test the integration"
echo ""
echo "Terminal 1: Watch logs"
echo "  kubectl -n airflow logs -l app=pachyderm-webhook -f"
echo ""
echo "Terminal 2: Upload file"
echo "  ffmpeg -f lavfi -i testsrc=s=640x480:d=1 -f lavfi -i sine -t 1 /tmp/test.mp4"
echo "  pachctl put file media@master:/incoming/test-001/test.mp4 -f /tmp/test.mp4"
echo ""
echo "Terminal 3: Watch Airflow"
echo "  kubectl -n airflow port-forward svc/airflow-webserver 8080:8080"
echo "  # Open http://localhost:8080/dags/ingest_pipeline/grid"
echo ""

echo "=========================================="
echo "Done! Webhook should now be active."
echo "=========================================="
echo ""
echo "For detailed information, see:"
echo "  - babelapha/CONTROL_NODE_DEPLOYMENT.md"
echo "  - babelapha/pipelines/airflow/WEBHOOK_SETUP.md"
echo ""
