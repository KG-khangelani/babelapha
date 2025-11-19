# Pachyderm → Airflow Webhook Setup (One-Liner Reference)

## Deploy Webhook
```bash
kubectl apply -f pipelines/airflow/webhook-deployment.yaml && kubectl -n airflow wait --for=condition=ready pod -l app=pachyderm-webhook --timeout=60s
```

## Configure Pachyderm Notification
```bash
pachctl notification create --name ingest-pipeline-trigger --repo media --branch master --trigger commit --webhook-url http://pachyderm-webhook.airflow:8000/webhook/pachyderm
```

## Test Upload
```bash
ffmpeg -f lavfi -i testsrc=s=640x480:d=1 -f lavfi -i sine=f=1000:d=1 -t 1 /tmp/test.mp4 && \
pachctl put file media@master:/incoming/test-001/test.mp4 -f /tmp/test.mp4
```

## Monitor
```bash
# Terminal 1: Webhook logs
kubectl -n airflow logs -l app=pachyderm-webhook -f

# Terminal 2: Airflow UI
kubectl -n airflow port-forward svc/airflow-webserver 8080:8080
# Open http://localhost:8080/dags/ingest_pipeline/grid

# Terminal 3: Verify notification exists
pachctl notification list --repo media
```

## Verify Webhook Endpoint
```bash
# From cluster (if you have kubectl access)
kubectl -n airflow port-forward svc/pachyderm-webhook 8000:8000
curl http://localhost:8000/health
curl http://localhost:8000/webhook/pachyderm

# From Pachyderm pod (to verify it can reach webhook)
kubectl -n pachyderm exec deployment/pachd -- curl http://pachyderm-webhook.airflow:8000/health
```

## Cleanup
```bash
pachctl notification delete --repo media ingest-pipeline-trigger && \
kubectl delete -f pipelines/airflow/webhook-deployment.yaml
```

## Logs & Debugging
```bash
# Webhook pod logs
kubectl -n airflow logs -l app=pachyderm-webhook --tail=50

# Airflow scheduler logs
kubectl -n airflow logs -l app=airflow,component=scheduler --tail=50

# Check if DAG run was created
kubectl -n airflow exec deployment/airflow-scheduler -- \
  airflow dags list-runs --dag-id ingest_pipeline | head -10
```
