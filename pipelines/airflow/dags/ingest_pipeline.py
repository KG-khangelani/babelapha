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
        namespace="airflow",
        image="clamav:latest",
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf.get('id', 'default-id') }}",
            "SRC_PATH": "/incoming/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "DEST_PATH": "/clean/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
        },
        secrets=[pach_token],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=True,
        image_pull_policy="IfNotPresent",  # Use local images if available
        node_selector={"kubernetes.io/arch": "amd64"},  # Require x86_64 nodes (ClamAV not available on ARM64)
    )

    # -------------------------------
    # Validation (FFprobe + MediaInfo)
    # -------------------------------
    validate_media = KubernetesPodOperator(
        task_id="validate_media",
        name="validate-media",
        namespace="airflow",
        image="validate:latest",
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf.get('id', 'default-id') }}",
            "SRC_PATH": "/clean/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "DEST_PATH": "/validated/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "REPORT_PATH": "/reports/{{ dag_run.conf.get('id', 'default-id') }}/validation.json",
        },
        secrets=[pach_token],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=True,
        image_pull_policy="IfNotPresent",  # Use local images if available
        node_selector={"kubernetes.io/arch": "amd64"},  # Require x86_64 nodes
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
        namespace="airflow",
        image="transcode:latest",
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf.get('id', 'default-id') }}",
            "SRC_PATH": "/validated/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "DEST_PATH": "/transcoded/{{ dag_run.conf.get('id', 'default-id') }}",
            "OUTPUT_FORMATS": "hls,dash",
        },
        secrets=[pach_token],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=True,
        image_pull_policy="IfNotPresent",  # Use local images if available
        node_selector={"kubernetes.io/arch": "amd64"},  # Require x86_64 nodes
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