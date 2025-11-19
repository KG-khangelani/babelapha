# Webhook Deployment Complete!

## ✅ Webhook Service Deployed

The webhook listener has been successfully deployed to the Kubernetes cluster on the control node:

### Deployment Status
- **Service**: `pachyderm-webhook` in `airflow` namespace  
- **Replicas**: 2 running (READY: 1/1 each)
- **Port**: 8000 (accessible at `http://pachyderm-webhook.airflow:8000`)
- **Endpoints**: `10.244.2.78:8000`, `10.244.4.39:8000`

### Endpoints Available
- `GET /health` - Health check endpoint
- `GET /webhook/pachyderm` - Webhook status endpoint  
- `POST /webhook/pachyderm` - Webhook event receiver (for Pachyderm commits)

### How It Works
1. Pachyderm sends PUT_FILE events to `http://pachyderm-webhook.airflow:8000/webhook/pachyderm`
2. Webhook extracts metadata from file path: `/incoming/<id>/<filename>`
3. Webhook triggers Airflow `ingest_pipeline` DAG with metadata as config
4. DAG runs media processing pipeline (virus scan → validate → transcode)

## 📋 Next Steps: Configure Pachyderm Notifications

The webhook service is running and ready to receive events. To complete the integration:

### 1. Check Pachyderm Webhook Support
Current Pachyderm version: **2.8.0-alpha**  
The `pachctl notification` command is not available in this alpha version.

### 2. Alternative: Manual Testing
Test the webhook manually by sending a POST request:

```bash
# From outside cluster
kubectl -n airflow port-forward svc/pachyderm-webhook 8001:8000 &

curl -X POST http://localhost:8001/webhook/pachyderm \
  -H "Content-Type: application/json" \
  -d '{
    "action": "put_file",
    "path": "/incoming/test-001/test.mp4"
  }'
```

### 3. Production Integration
Once Pachyderm webhook support is confirmed, create the notification:

```bash
pachctl notification create \
  --name ingest-pipeline-trigger \
  --repo media/media \
  --branch master \
  --trigger commit \
  --webhook-url http://pachyderm-webhook.airflow:8000/webhook/pachyderm
```

## 🔧 Service Configuration

ConfigMap: `pachyderm-webhook-config` (environment variables)
- `AIRFLOW_API_URL`: http://airflow-webserver.airflow:8080/api/v1
- `WEBHOOK_PORT`: 8000
- `DEBUG`: false

Code: `webhook-listener-code` ConfigMap
- Uses Python 3.11 stdlib only (no external dependencies)
- Handles Pachyderm PUT_FILE events
- Triggers Airflow DAG via REST API
- Non-blocking execution with threading

## 📊 Monitoring

### View Logs
```bash
kubectl -n airflow logs -l app=pachyderm-webhook -f
```

### Check Service
```bash
kubectl -n airflow get svc pachyderm-webhook
kubectl -n airflow get endpoints pachyderm-webhook
```

### Test Health
```bash
kubectl -n airflow exec <pod-name> -- python3 -c \
  "import urllib.request as u; \
   r = u.urlopen('http://localhost:8000/health'); \
   print(r.read().decode())"
```

## 📁 Repository Structure

All webhook code is committed to `babelapha` repository:
- `pipelines/airflow/webhook_listener_stdlib.py` - Main webhook service
- `pipelines/airflow/webhook-deployment.yaml` - K8s manifests
- `pipelines/airflow/WEBHOOK_SETUP.md` - Full setup guide

Control node infrastructure is in `khancreate_infra` repository:
- `webhook-deployment/` - Deployment configs and scripts

## 🚀 Ready for Testing

The webhook service is operational and waiting to receive events from Pachyderm. Once Pachyderm webhook notifications are configured, file uploads to `/incoming/` will automatically trigger the ingest_pipeline DAG.

---
**Last Updated**: November 19, 2025  
**Status**: ✅ Deployment Complete - Awaiting Pachyderm Integration
