# Pachyderm → Airflow DAG Triggering Setup

This document describes how to automatically trigger the `ingest_pipeline` DAG when files are uploaded to the Pachyderm `media` repository.

## Architecture

```
┌─────────────────────────┐
│  Pachyderm Namespace    │
│  (pachyderm)            │
│                         │
│  media@master:/incoming │ (Put file event)
│         │               │
│         │ notification  │
│         └──────────────────────┐
│                         │      │
└─────────────────────────┘      │ HTTP POST
                                 │
                    ┌────────────▼─────────────┐
                    │  Airflow Namespace       │
                    │  (airflow)               │
                    │                          │
                    │  pachyderm-webhook pod   │
                    │  ├─ Receives notifications
                    │  ├─ Parses file metadata │
                    │  └─ Triggers DAG via API │
                    │                          │
                    │  airflow-scheduler       │
                    │  └─ Runs ingest_pipeline │
                    │                          │
                    └──────────────────────────┘
```

## Components

### 1. Webhook Listener Service
- **Image**: python:3.11-slim (Flask HTTP server)
- **Namespace**: airflow
- **Service**: pachyderm-webhook (ClusterIP on port 8000)
- **Replicas**: 2 (for redundancy)
- **Endpoint**: `http://pachyderm-webhook.airflow:8000/webhook/pachyderm`

### 2. Pachyderm Notification Rule
- **Trigger**: Commit events on `media` repo, `master` branch
- **Target**: HTTP webhook URL pointing to Airflow webhook service
- **Action**: On PUT_FILE events in `/incoming/` path, trigger ingest_pipeline

### 3. Airflow DAG
- **DAG ID**: `ingest_pipeline`
- **Schedule**: Manual/Webhook triggered
- **Config Required**: 
  - `id`: Object identifier (e.g., "test-001")
  - `filename`: Media file name (e.g., "sample.mp4")

## Installation

### Step 1: Deploy Webhook Listener

Deploy the webhook listener in the Airflow namespace:

```bash
kubectl apply -f pipelines/airflow/webhook-deployment.yaml
```

Verify deployment:

```bash
kubectl -n airflow get pods -l app=pachyderm-webhook
kubectl -n airflow logs -l app=pachyderm-webhook --tail=20
```

Test webhook health:

```bash
kubectl -n airflow port-forward svc/pachyderm-webhook 8000:8000 &
curl http://localhost:8000/health
curl http://localhost:8000/webhook/pachyderm
```

### Step 2: Configure Pachyderm Notification

Run the setup script from the control node:

```bash
cd /path/to/babelapha
bash pipelines/airflow/setup-pachyderm-notification.sh
```

**Or manually configure** using pachctl:

```bash
pachctl notification create \
  --name ingest-pipeline-trigger \
  --repo media \
  --branch master \
  --trigger commit \
  --webhook-url http://pachyderm-webhook.airflow:8000/webhook/pachyderm
```

Verify notification was created:

```bash
pachctl notification list --repo media
```

Expected output:
```
NAME                         REPO   BRANCH   TRIGGER
ingest-pipeline-trigger      media  master   commit
```

## Testing the Integration

### Test 1: Manual File Upload

Upload a test file to Pachyderm:

```bash
# Create a small test video (or use existing)
ffmpeg -f lavfi -i testsrc=s=640x480:d=1 -f lavfi -i sine=f=1000:d=1 /tmp/test.mp4

# Upload to Pachyderm
pachctl put file media@master:/incoming/test-001/test.mp4 -f /tmp/test.mp4
```

### Test 2: Monitor Webhook

In a separate terminal, watch webhook logs:

```bash
kubectl -n airflow logs -l app=pachyderm-webhook -f
```

You should see:
```
[2025-11-19 10:15:23] INFO: Received Pachyderm webhook: {...}
[2025-11-19 10:15:23] INFO: Extracted metadata: {'id': 'test-001', 'filename': 'test.mp4'}
[2025-11-19 10:15:23] INFO: Triggering DAG with payload: {...}
[2025-11-19 10:15:23] INFO: ✓ DAG triggered successfully: run_id=ingest_pipeline_20251119T101523_abc123
```

### Test 3: Check Airflow DAG Run

Access Airflow UI:

```bash
kubectl -n airflow port-forward svc/airflow-webserver 8080:8080 &
# Open http://localhost:8080 in browser
```

Navigate to:
- **DAG**: ingest_pipeline
- Look for recent run with **Conf** showing: `{"id": "test-001", "filename": "test.mp4"}`

### Test 4: View Task Logs

Once DAG runs, check task execution:

```bash
# List running pods
kubectl -n airflow get pods

# Check task logs
kubectl -n airflow logs -f <pod-name>
```

## Webhook Event Format

The webhook expects Pachyderm commit notifications in the following format:

```json
{
  "action": "put_file",
  "path": "/incoming/object-id/filename.ext",
  "commit": {
    "branch": {
      "repo": {
        "name": "media"
      },
      "name": "master"
    },
    "id": "commit-hash"
  }
}
```

The webhook listener:
1. Validates the action is `put_file`
2. Extracts path: `/incoming/<id>/<filename>`
3. Parses into metadata: `{"id": "...", "filename": "..."}`
4. POSTs to Airflow API: `/api/v1/dags/ingest_pipeline/dagRuns`
5. Logs result and returns HTTP 202 (Accepted)

## Troubleshooting

### Webhook pod not starting

```bash
kubectl -n airflow describe pod <webhook-pod-name>
kubectl -n airflow logs <webhook-pod-name>
```

**Issue**: Image pull failures
- **Solution**: Pre-pull image or use local image with ImagePullPolicy: Never

**Issue**: Port already in use
- **Solution**: Change webhook port in ConfigMap

### No DAG run triggered after file upload

1. **Verify notification exists**:
   ```bash
   pachctl notification list --repo media
   ```

2. **Check webhook logs**:
   ```bash
   kubectl -n airflow logs -l app=pachyderm-webhook --tail=100
   ```

3. **Verify Pachyderm can reach webhook**:
   ```bash
   kubectl -n pachyderm exec <pachd-pod> -- \
     curl -v http://pachyderm-webhook.airflow:8000/health
   ```

4. **Check Airflow API availability**:
   ```bash
   kubectl -n airflow port-forward svc/airflow-webserver 8080:8080
   curl http://localhost:8080/api/v1/dags
   ```

### DAG run created but not executing

1. **Check Airflow logs**:
   ```bash
   kubectl -n airflow logs -l app=airflow-scheduler | grep ingest_pipeline
   ```

2. **Verify DAG syntax**:
   ```bash
   kubectl -n airflow exec <airflow-pod> -- \
     airflow dags test ingest_pipeline
   ```

3. **Check Pachyderm token secret**:
   ```bash
   kubectl -n airflow get secret pach-auth-media
   ```

## Configuration Reference

### Webhook Listener Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AIRFLOW_API_URL` | `http://airflow-webserver.airflow:8080/api/v1` | Airflow API endpoint |
| `WEBHOOK_PORT` | `8000` | Port to listen on |
| `DEBUG` | `false` | Enable debug logging |

### Pachyderm Paths

| Path | Purpose |
|------|---------|
| `/incoming/<id>/<filename>` | Upload source (triggers DAG) |
| `/clean/<id>/<filename>` | After virus scan passes |
| `/validated/<id>/<filename>` | After media validation passes |
| `/transcoded/<id>/` | Final HLS/DASH output |
| `/quarantine/<id>/<filename>` | If validation fails |
| `/reports/<id>/` | JSON reports from each stage |

## Advanced: Custom Path Handling

To support different upload paths (e.g., `/uploads/` instead of `/incoming/`), modify the webhook listener:

```python
# In webhook_listener.py
PACH_INCOMING_PATH = "/uploads"  # Change this line

# Or make it configurable:
PACH_INCOMING_PATH = os.environ.get("PACH_INCOMING_PATH", "/incoming")
```

Then redeploy with updated ConfigMap.

## Performance Notes

- Webhook processes events sequentially; ~1-2s per event
- Airflow API call typically completes in <200ms
- DAG runs should start within 10-30 seconds of webhook receipt
- Multiple file uploads will trigger multiple DAG runs (parallel execution up to `max_active_runs: 8`)

## Security Considerations

1. **Authentication**: Webhook endpoint is currently open. To secure:
   - Add HMAC signature verification from Pachyderm
   - Restrict webhook service to ClusterIP (default)
   - Use network policies if needed

2. **Pachyderm Token**: Stored in Kubernetes Secret, mounted at container runtime

3. **API Token**: Airflow API uses default authentication (consider adding API tokens)

## Cleanup

To remove the integration:

```bash
# Remove Pachyderm notification
pachctl notification delete --repo media ingest-pipeline-trigger

# Remove Airflow webhook deployment
kubectl delete -f pipelines/airflow/webhook-deployment.yaml
```
