from airflow.decorators import dag, task
from datetime import datetime, timedelta
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.cncf.kubernetes.secret import Secret
from kubernetes.client import models as k8s
import os

# =====================================================================
# DAG: ingest_pipeline
# Purpose:
#   Orchestrates upload → scan → validate → transcode using Pachyderm
#   Uses PUBLIC base images with scripts injected via ConfigMaps
#   No custom image builds required
# =====================================================================

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
            "PYTHONPATH": "/app",
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
    # Uses public docker.io/clamav/clamav:latest
    # Injects scan.py via ConfigMap
    # -------------------------------
    virus_scan = KubernetesPodOperator(
        task_id="virus_scan",
        name="clamav-scan",
        namespace="airflow",
        image="docker.io/clamav/clamav:latest",
        image_pull_policy="Always",
        command=["python3"],
        arguments=["/app/scan.py"],
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf.get('id', 'default-id') }}",
            "SRC_PATH": "/incoming/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "DEST_PATH": "/clean/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "PYTHONPATH": "/app",
        },
        secrets=[pach_token],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=True,
        volume_mounts=[
            k8s.V1VolumeMount(name="clamav-script", mount_path="/app", read_only=True),
            k8s.V1VolumeMount(name="utils-script", mount_path="/app/utils", read_only=True),
        ],
        volumes=[
            k8s.V1Volume(name="clamav-script", config_map=k8s.V1ConfigMapVolumeSource(name="ingest-clamav-script")),
            k8s.V1Volume(name="utils-script", config_map=k8s.V1ConfigMapVolumeSource(name="ingest-utils-script")),
        ],
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    # -------------------------------
    # Validation (FFprobe + MediaInfo)
    # Uses public docker.io/jrottenberg/ffmpeg:6.1-ubuntu
    # Injects validate.py via ConfigMap
    # -------------------------------
    validate_media = KubernetesPodOperator(
        task_id="validate_media",
        name="validate-media",
        namespace="airflow",
        image="docker.io/jrottenberg/ffmpeg:6.1-ubuntu",
        image_pull_policy="Always",
        command=["python3"],
        arguments=["/app/validate.py"],
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf.get('id', 'default-id') }}",
            "SRC_PATH": "/clean/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "DEST_PATH": "/validated/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "REPORT_PATH": "/reports/{{ dag_run.conf.get('id', 'default-id') }}/validation.json",
            "PYTHONPATH": "/app",
        },
        secrets=[pach_token],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=True,
        volume_mounts=[
            k8s.V1VolumeMount(name="ffmpeg-script", mount_path="/app", read_only=True),
            k8s.V1VolumeMount(name="utils-script", mount_path="/app/utils", read_only=True),
        ],
        volumes=[
            k8s.V1Volume(name="ffmpeg-script", config_map=k8s.V1ConfigMapVolumeSource(name="ingest-ffmpeg-script")),
            k8s.V1Volume(name="utils-script", config_map=k8s.V1ConfigMapVolumeSource(name="ingest-utils-script")),
        ],
        node_selector={"kubernetes.io/arch": "amd64"},
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
    # Uses public docker.io/jrottenberg/ffmpeg:6.1-ubuntu
    # Injects transcode.py via ConfigMap
    # -------------------------------
    transcode = KubernetesPodOperator(
        task_id="transcode",
        name="transcode",
        namespace="airflow",
        image="docker.io/jrottenberg/ffmpeg:6.1-ubuntu",
        image_pull_policy="Always",
        command=["python3"],
        arguments=["/app/transcode.py"],
        env_vars={
            **base_env(),
            "OBJ_ID": "{{ dag_run.conf.get('id', 'default-id') }}",
            "SRC_PATH": "/validated/{{ dag_run.conf.get('id', 'default-id') }}/{{ dag_run.conf.get('filename', 'default.mp4') }}",
            "DEST_PATH": "/transcoded/{{ dag_run.conf.get('id', 'default-id') }}",
            "OUTPUT_FORMATS": "hls,dash",
            "PYTHONPATH": "/app",
        },
        secrets=[pach_token],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=True,
        volume_mounts=[
            k8s.V1VolumeMount(name="ffmpeg-script", mount_path="/app", read_only=True),
            k8s.V1VolumeMount(name="utils-script", mount_path="/app/utils", read_only=True),
        ],
        volumes=[
            k8s.V1Volume(name="ffmpeg-script", config_map=k8s.V1ConfigMapVolumeSource(name="ingest-ffmpeg-script")),
            k8s.V1Volume(name="utils-script", config_map=k8s.V1ConfigMapVolumeSource(name="ingest-utils-script")),
        ],
        node_selector={"kubernetes.io/arch": "amd64"},
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