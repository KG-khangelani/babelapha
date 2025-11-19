# Airflow Pipelines

This directory contains Airflow DAGs that orchestrate the media ingestion and
processing workflows. The current focus is a single `ingest_pipeline` DAG that
models the high-level steps required to take a raw interview recording and
produce a transcript with associated metadata.

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
   pip install "apache-airflow[celery]==2.9.1"
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

1. **virus_scan** (ClamAV): Scans uploaded file for malware
   - Input: `/incoming/<id>/<filename>`
   - Output: `/clean/<id>/<filename>` (if clean) or `/quarantine/<id>/<filename>`
   - Report: `/reports/<id>/clamav.json`

2. **validate_media** (FFprobe + MediaInfo): Validates media properties
   - Input: `/clean/<id>/<filename>`
   - Output: `/validated/<id>/<filename>` (if valid) or `/quarantine/<id>/<filename>`
   - Report: `/reports/<id>/validation.json`

3. **route_decision**: Routes based on validation results (placeholder)

4. **transcode** (FFmpeg): Generates HLS/DASH renditions
   - Input: `/validated/<id>/<filename>`
   - Output: `/transcoded/<id>/hls/` and `/transcoded/<id>/dash/`
   - Report: `/reports/<id>/transcode.json`

All file operations use Pachyderm S3 gateway for seamless integration with the `media` repo.

The individual task implementations use Docker containers for isolation and 
Kubernetes Pod Operator for execution on your Airflow cluster.
