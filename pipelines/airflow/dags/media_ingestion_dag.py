"""Media ingestion DAG.

This DAG is the starting point for the interview processing pipeline. It
stitches together the high-level tasks that move media assets from MinIO into
versioned datasets with derived transcripts and metadata.

The DAG is intentionally lightweight: operators call simple Python functions so
that local development works without a fully fledged Airflow deployment. As the
project matures, replace the placeholder implementations with production-grade
logic (e.g. ECS tasks, Pachyderm triggers, etc.).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator


def _upload_to_minio(**context):
    """Pretend to upload a raw interview file to MinIO."""
    dag_run = context.get("dag_run")
    interview_id = (dag_run and dag_run.conf.get("interview_id")) or "demo-interview"
    print(f"Uploading assets for {interview_id} to MinIO ...")


def _extract_audio(**context):
    """Placeholder for an audio extraction step."""
    print("Extracting audio track from uploaded video ...")


def _transcribe_audio(**context):
    """Placeholder for the transcription service."""
    print("Transcribing audio track and storing transcript artifact ...")


def _store_metadata(**context):
    """Placeholder for storing derived metadata into Pachyderm."""
    print("Writing metadata to Pachyderm versioned dataset ...")


default_args = {
    "owner": "babelapha",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="media_ingestion",
    description="Prototype media ingestion workflow for interview assets",
    default_args=default_args,
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["media", "transcription", "prototype"],
) as dag:
    upload = PythonOperator(
        task_id="upload_to_minio",
        python_callable=_upload_to_minio,
    )

    extract_audio = PythonOperator(
        task_id="extract_audio",
        python_callable=_extract_audio,
    )

    transcribe = PythonOperator(
        task_id="transcribe_audio",
        python_callable=_transcribe_audio,
    )

    store_metadata = PythonOperator(
        task_id="store_metadata",
        python_callable=_store_metadata,
    )

    upload >> extract_audio >> transcribe >> store_metadata
