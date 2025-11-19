from airflow.decorators import dag, task
from datetime import datetime, timedelta
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.cncf.kubernetes.secret import Secret
from kubernetes.client import models as k8s
import os

default_args = dict(retries=2)

@dag(
    dag_id="ingest_pipeline",
    description="Media ingestion and processing flow integrated with Pachyderm",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media"],
)
def ingest_pipeline():
    def base_env():
        return {
            "PACH_S3_ENDPOINT": os.environ.get("PACH_S3_ENDPOINT", "http://pachd-proxy-backend.pachyderm:1600"),
            "PACH_S3_PREFIX": os.environ.get("PACH_S3_PREFIX", "s3://pach/media/master"),
            "PFS_REPO": "media",
            "PFS_BRANCH": "master",
            "PYTHONPATH": "/app",
        }

    pach_token = Secret(deploy_type="env", deploy_target="PACH_TOKEN", secret="pach-auth-media", key="token")

    @task
    def start():
        return "Starting pipeline"

    virus_scan = KubernetesPodOperator(
        task_id="virus_scan",
        name="clamav-scan",
        namespace="airflow",
        image="docker.io/clamav/clamav:latest",
        image_pull_policy="Always",
        container_kwargs={
            "command": ["python3"],
            "args": ["/app/scan.py"],
        },
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

    validate_media = KubernetesPodOperator(
        task_id="validate_media",
        name="validate-media",
        namespace="airflow",
        image="docker.io/jrottenberg/ffmpeg:6.1-ubuntu",
        image_pull_policy="Always",
        container_kwargs={
            "command": ["python3"],
            "args": ["/app/validate.py"],
        },
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

    @task
    def route_decision(**context):
        return "transcode"

    transcode = KubernetesPodOperator(
        task_id="transcode",
        name="transcode",
        namespace="airflow",
        image="docker.io/jrottenberg/ffmpeg:6.1-ubuntu",
        image_pull_policy="Always",
        container_kwargs={
            "command": ["python3"],
            "args": ["/app/transcode.py"],
        },
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

    @task
    def end():
        return "Pipeline complete"

    start() >> virus_scan >> validate_media >> route_decision() >> transcode >> end()

ingest_pipeline()
