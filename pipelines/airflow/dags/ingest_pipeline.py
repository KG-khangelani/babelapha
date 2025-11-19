"""
Minimal test version of ingest pipeline.

This version focuses on testing the KubernetesPodOperator configuration
without external dependencies (network, packages, etc).

Key fixes applied:
1. Removed is_delete_operator_pod=True (can mask exit codes)
2. Removed unnecessary volumes/secrets for testing
3. Using simple Python inline commands instead of external scripts
4. Each task is self-contained with minimal dependencies
5. Deferred KubernetesPodOperator import to avoid slow provider initialization
"""
from airflow.sdk import dag, task

default_args = dict(retries=1)

@dag(
    dag_id="ingest_pipeline",
    description="Media ingestion pipeline (test version)",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media"],
)
def ingest_pipeline():
    """Minimal ingest pipeline for testing."""
    # Deferred import to avoid slow provider manager initialization during DAG parsing
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

    @task
    def start():
        """Start marker."""
        print("[START] Pipeline initialized")
        return "started"

    # Simple test: Just echo and exit cleanly
    virus_scan = KubernetesPodOperator(
        task_id="virus_scan",
        name="virus-scan",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3"],
        arguments=[
            "-c",
            "import sys; print('[virus_scan] Complete'); sys.exit(0)"
        ],
        in_cluster=True,
        get_logs=True,
        # IMPORTANT: Don't delete pod - helps with debugging
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    validate_media = KubernetesPodOperator(
        task_id="validate_media",
        name="validate-media",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3"],
        arguments=[
            "-c",
            "import sys; print('[validate_media] Complete'); sys.exit(0)"
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    transcode = KubernetesPodOperator(
        task_id="transcode",
        name="transcode",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3"],
        arguments=[
            "-c",
            "import sys; print('[transcode] Complete'); sys.exit(0)"
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    @task
    def end(result):
        """End marker."""
        print(f"[END] Pipeline completed: {result}")
        return "completed"

    # Simple linear pipeline for now
    start() >> virus_scan >> validate_media >> transcode >> end("success")

ingest_pipeline()





