from airflow.decorators import dag, task
from datetime import datetime, timedelta
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.cncf.kubernetes.secret import Secret
import os

# ---------------------------------------------------------------------
# DAG: ingest_pipeline
# Purpose:
#   Orchestrates upload → scan → validate → transcode using Pachyderm repo 'media'
#   Files are moved between logical state paths within a single repo (no duplication)
# ---------------------------------------------------------------------

default_args = dict(retries=2)

@dag(
    dag_id="ingest_pipeline",
    description="Media ingestion and processing flow integrated with Pachyderm",
    # start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media"],
)
def ingest_pipeline():
    # -------------------------------
    # Helper: common environment vars
    # -------------------------------
    def base_env():
        return {
            # Fix default endpoint hostname typo (pachyderm)
            "PACH_S3_ENDPOINT": os.environ.get("PACH_S3_ENDPOINT", "http://pachd-proxy-backend.pachyderm:1600"),
            "PACH_S3_PREFIX": os.environ.get("PACH_S3_PREFIX", "s3://pach/media/master"),
            "PFS_REPO": "media",
            "PFS_BRANCH": "master",
        }

    pach_token = Secret(deploy_type="env", deploy_target="PACH_TOKEN", secret="pach-auth-media", key="token")

    # -------------------------------
    # DAG start
    # -------------------------------
    @task
    def start():
        return "Starting pipeline"

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
        secrets=[pach_token],
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
        secrets=[pach_token],
        get_logs=True,
        is_delete_operator_pod=True,
    )

    # -------------------------------
    # Route Decision (placeholder)
    # Could read report JSON to decide to quarantine or proceed to transcode
    # For now: always proceed to transcode
    # -------------------------------
    @task
    def route_decision(**context):
        # Example logic for future use:
        # reports_path = f"/reports/{context['dag_run'].conf['id']}/validation.json"
        # read from PFS if needed
        return "transcode"

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
        secrets=[pach_token],
        get_logs=True,
        is_delete_operator_pod=True,
    )

    # -------------------------------
    # DAG end
    # -------------------------------
    @task
    def end():
        return "Pipeline complete"

    # DAG structure
    start() >> virus_scan >> validate_media >> route_decision() >> transcode >> end()

# Instantiate the DAG
ingest_pipeline()
# inja madoda