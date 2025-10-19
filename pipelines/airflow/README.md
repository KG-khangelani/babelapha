# Airflow Pipelines

This directory contains Airflow DAGs that orchestrate the media ingestion and
processing workflows. The current focus is a single `media_ingestion` DAG that
models the high-level steps required to take a raw interview recording and
produce a transcript with associated metadata.

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
   airflow dags trigger media_ingestion --conf '{"interview_id": "demo-interview"}'
   ```

The individual task implementations are placeholders. Replace them with real
logic (for example, shelling out to ffmpeg or calling the transcription service)
as those components become available.
