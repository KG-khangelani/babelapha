# Airflow Pipelines

This directory contains Airflow DAGs that orchestrate media ingestion and emit
immutable provenance evidence plus OpenLineage events. `ingest_pipeline` is the
production Kubernetes flow; `ingest_pipeline_local` is the Docker Compose flow.

## Triggering Methods

### Method 1: Automatic Trigger (Pachyderm Webhook)

The DAG is automatically triggered when files are uploaded to the Pachyderm `media` repository.

**Setup**: See [WEBHOOK_SETUP.md](WEBHOOK_SETUP.md) for installation and configuration.

**How it works**:
1. Pachyderm detects a file upload to `/incoming/<id>/<filename>`
2. Sends HTTP POST to webhook service in Airflow namespace
3. Webhook parses the path and extracts `id` and `filename`
4. Webhook triggers `ingest_pipeline` DAG via Airflow REST API with the metadata

**To test**:
```bash
# Upload a file to Pachyderm
pachctl put file media@master:/incoming/test-001/sample.mp4 -f /path/to/sample.mp4

# DAG should automatically trigger within 10-30 seconds
# Check Airflow UI: http://localhost:8080
```

### Method 2: Manual REST API

Trigger the DAG using Airflow REST API:

```bash
curl -X POST http://localhost:8080/api/v1/dags/ingest_pipeline/dagRuns \
  -H "Content-Type: application/json" \
  -d '{
    "conf": {
      "id": "test-001",
      "filename": "sample.mp4"
    }
  }'
```

Or use the provided Python script:

```bash
python trigger_dag_run.py
```

### Method 3: Airflow CLI

Trigger using the Airflow command line (local or pod):

```bash
airflow dags trigger ingest_pipeline --conf '{"id": "demo-id", "filename": "sample.mp4"}'
```

## Local Development

1. Create a Python virtual environment and install Airflow:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
pip install "apache-airflow[celery]==3.3.1" --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.11.txt"
   ```

2. Export the DAGs folder so Airflow can find the DAG:
   ```bash
   export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/dags
   airflow standalone
   ```

3. Trigger the DAG manually:
   ```bash
   airflow dags trigger ingest_pipeline --conf '{"id": "demo-id", "filename": "sample.mp4"}'
   ```

## Architecture

**ingest_pipeline** stages:

1. **validate_inputs**: validates the event contract.
2. **inspect_source**: streams the source and establishes its SHA-256, size,
   object version, ETag, and optional Pachyderm commit.
3. **virus_scan** (ClamAV): independently downloads and verifies the source,
   then records the malware decision.
4. **validate_media** (FFprobe): independently verifies the source and records
   the format decision.
5. **transcode** (FFmpeg): creates HLS/DASH, hashes every output, and uploads
   each object with its SHA-256 metadata.
6. **verify_outputs**: reads every stored output back and verifies its bytes.
7. **mark_complete** and **verify_provenance**: close the run only after all
   required immutable success manifests exist.

All attempts—including failed retries—are stored under
`provenance/<object-id>/<run-id>/`. See
[`../../Documentation/pipeline-transparency.md`](../../Documentation/pipeline-transparency.md)
for the contract and exact-identity requirements.
