from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.empty import EmptyOperator
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator
from airflow.operators.python import PythonOperator
import os

# ---------------------------------------------------------------------
# DAG: ingest_pipeline
# Purpose:
#   Orchestrates upload → scan → validate → transcode using Pachyderm repo 'media'
#   Files are moved between logical state paths within a single repo (no duplication)
# ---------------------------------------------------------------------

default_args = dict(retries=2)

with DAG(
    dag_id="ingest_pipeline",
    description="Media ingestion and processing flow integrated with Pachyderm",
    start_date=days_ago(1),
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media"],
) as dag:

    # -------------------------------
    # Helper: common environment vars
    # -------------------------------
    def base_env():
        return {
            "PACH_S3_ENDPOINT": os.environ.get("PACH_S3_ENDPOINT", "http://pach-s3.pachd:30600"),
            "PACH_S3_PREFIX": os.environ.get("PACH_S3_PREFIX", "s3://pach/media/master"),
            "PACH_TOKEN": os.environ.get("PACH_TOKEN", ""),
            "PFS_REPO": "media",
            "PFS_BRANCH": "master",
        }

    # -------------------------------
    # DAG start
    # -------------------------------
    start = EmptyOperator(task_id="start")

    # -------------------------------
    # Virus Scan (ClamAV)
    # -------------------------------
    virus_scan = KubernetesPodOperator(
        task_id="virus_scan",
        name="clamav-scan",
        image="ghcr.io/you/clamav:latest",
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf['id'] }}",
            "SRC_PATH": "/incoming/{{ dag_run.conf['id'] }}/{{ dag_run.conf['filename'] }}",
        },
        get_logs=True,
        is_delete_operator_pod=True,
    )

    # -------------------------------
    # Validation (FFprobe + MediaInfo)
    # -------------------------------
    validate_media = KubernetesPodOperator(
        task_id="validate_media",
        name="validate-media",
        image="ghcr.io/you/validate:latest",
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf['id'] }}",
            "SRC_PATH": "/scanned/{{ dag_run.conf['id'] }}/{{ dag_run.conf['filename'] }}",
        },
        get_logs=True,
        is_delete_operator_pod=True,
    )

    # -------------------------------
    # Route Decision (placeholder)
    # Could read report JSON to decide to quarantine or proceed to transcode
    # For now: always proceed to transcode
    # -------------------------------
    def route_decision(**context):
        # Example logic for future use:
        # reports_path = f"/reports/{context['dag_run'].conf['id']}/validation.json"
        # read from PFS if needed
        return "transcode"

    route = PythonOperator(
        task_id="route_decision",
        python_callable=route_decision,
    )

    # -------------------------------
    # Transcode (HLS/DASH)
    # -------------------------------
    transcode = KubernetesPodOperator(
        task_id="transcode",
        name="transcode",
        image="ghcr.io/you/transcode:latest",
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf['id'] }}",
            "SRC_PATH": "/validated/{{ dag_run.conf['id'] }}/{{ dag_run.conf['filename'] }}",
        },
        get_logs=True,
        is_delete_operator_pod=True,
    )

    # -------------------------------
    # DAG end
    # -------------------------------
    end = EmptyOperator(task_id="end")

    # DAG structure
    start >> virus_scan >> validate_media >> route >> transcode >> end