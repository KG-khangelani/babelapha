# Webhook Deployment on Control Node (khancreate_infra)

This document describes how to deploy the Pachyderm → Airflow webhook using the infrastructure management repository.

## Prerequisites

- Control node: khangelani@192.168.10.104
- Babelapha repository cloned locally
- Access to ~/khancreate_infra on control node
- kubectl configured to access cluster

## Deployment Steps

### Step 1: Extract Webhook Files from Babelapha

On your local machine (Windows), copy the webhook files from babelapha:

```powershell
# From babelapha local repo
Copy-Item "h:\hikrepos\babelapha\pipelines\airflow\webhook_listener.py" -Destination "<khancreate_infra-workspace>\webhook_listener.py"
Copy-Item "h:\hikrepos\babelapha\pipelines\airflow\webhook-deployment.yaml" -Destination "<khancreate_infra-workspace>\webhook-deployment.yaml"
```

Or download them directly from GitHub:

```bash
# On control node
cd ~/khancreate_infra
wget https://raw.githubusercontent.com/KG-khangelani/babelapha/main/pipelines/airflow/webhook_listener.py
wget https://raw.githubusercontent.com/KG-khangelani/babelapha/main/pipelines/airflow/webhook-deployment.yaml
```

### Step 2: Deploy Webhook to Kubernetes

On control node (khangelani@192.168.10.104):

```bash
cd ~/khancreate_infra

# Create ConfigMap with webhook listener code
kubectl -n airflow create configmap webhook-listener-code \
    --from-file=webhook_listener.py=webhook_listener.py \
    --dry-run=client -o yaml | kubectl apply -f -

# Apply deployment manifest
kubectl apply -f webhook-deployment.yaml

# Wait for pods to be ready
kubectl -n airflow rollout status deployment/pachyderm-webhook --timeout=60s

# Verify pods are running
kubectl -n airflow get pods -l app=pachyderm-webhook
```

### Step 3: Configure Pachyderm Notification

On control node:

```bash
# Create the notification rule
pachctl notification create \
  --name ingest-pipeline-trigger \
  --repo media \
  --branch master \
  --trigger commit \
  --webhook-url http://pachyderm-webhook.airflow:8000/webhook/pachyderm

# Verify notification exists
pachctl notification list --repo media
```

### Step 4: Test the Integration

```bash
# Terminal 1: Watch webhook logs
kubectl -n airflow logs -l app=pachyderm-webhook -f

# Terminal 2: Upload a test file
ffmpeg -f lavfi -i testsrc=s=640x480:d=1 -f lavfi -i sine=f=1000:d=1 -t 1 /tmp/test.mp4
pachctl put file media@master:/incoming/test-001/test.mp4 -f /tmp/test.mp4

# Terminal 3: Check Airflow
kubectl -n airflow port-forward svc/airflow-webserver 8080:8080
# Open http://localhost:8080/dags/ingest_pipeline/grid
```

## File Locations

### On Control Node (khancreate_infra)
- `webhook_listener.py` - Webhook service code
- `webhook-deployment.yaml` - Kubernetes deployment manifest

### In Babelapha Repository (Local)
- `pipelines/airflow/webhook_listener.py` - Source code
- `pipelines/airflow/webhook-deployment.yaml` - Source manifest
- `pipelines/airflow/WEBHOOK_SETUP.md` - Detailed documentation
- `WEBHOOK_ONELINERS.md` - Quick reference commands

## Monitoring

From control node:

```bash
# View webhook service
kubectl -n airflow describe svc pachyderm-webhook

# Stream webhook logs
kubectl -n airflow logs -l app=pachyderm-webhook -f

# Check Pachyderm notifications
pachctl notification list --repo media

# Verify connectivity from Pachyderm
kubectl -n pachyderm exec deployment/pachd -- curl http://pachyderm-webhook.airflow:8000/health
```

## Troubleshooting

### Webhook pods not starting
```bash
kubectl -n airflow describe pod <webhook-pod>
kubectl -n airflow logs <webhook-pod>
```

### No events received from Pachyderm
```bash
# Verify notification exists
pachctl notification list --repo media

# Test webhook endpoint
kubectl -n airflow port-forward svc/pachyderm-webhook 8000:8000
curl http://localhost:8000/health
curl http://localhost:8000/webhook/pachyderm
```

### DAG not triggering
```bash
# Check Airflow API
kubectl -n airflow port-forward svc/airflow-webserver 8080:8080
curl http://localhost:8080/api/v1/dags

# Check Airflow logs
kubectl -n airflow logs -l app=airflow,component=scheduler --tail=50
```

## Infrastructure as Code

Store these files in khancreate_infra:

```
~/khancreate_infra/
├── webhook_listener.py          # Webhook service code
├── webhook-deployment.yaml      # Kubernetes manifests
└── pachyderm-webhook-config/    # Optional: environment configs
    └── dev.env
    └── prod.env
```

## Integration with Terraform/Tofu

If using Tofu/Terraform for infrastructure management, add resources:

```hcl
# kubernetes_manifest for webhook-deployment.yaml
resource "kubernetes_manifest" "webhook" {
  manifest = yamldecode(file("${path.module}/webhook-deployment.yaml"))
}

# kubernetes_config_map for webhook listener code
resource "kubernetes_config_map" "webhook_code" {
  metadata {
    name      = "webhook-listener-code"
    namespace = "airflow"
  }
  data = {
    "webhook_listener.py" = file("${path.module}/webhook_listener.py")
  }
}
```

## Notes

- Keep babelapha repo for code development and updates
- Use khancreate_infra for deployment and infrastructure management
- Update webhook code: pull latest from babelapha, copy to khancreate_infra
- Redeploy: recreate ConfigMap and restart pods
  ```bash
  kubectl -n airflow delete configmap webhook-listener-code
  # Rerun Step 2 above
  ```
