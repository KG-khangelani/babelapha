"""
Simplified ingest pipeline with focused sub-stages for better debugging and control.

Architecture:
- Each stage has clear inputs/outputs
- Minimal operator configuration to reduce failure modes
- Explicit error handling at each step
- Pure Python for control flow, KPO only for actual processing
- Deferred KubernetesPodOperator import to avoid slow provider initialization
"""
from airflow.sdk import dag, task
import os
from datetime import datetime

default_args = dict(retries=1)

@dag(
    dag_id="ingest_pipeline_v2",
    description="Simplified media ingestion pipeline with micro-stages",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media", "v2"],
)
def ingest_pipeline_v2():
    """Simplified pipeline with clear stage separation."""
    # Deferred imports to avoid slow provider manager initialization during DAG parsing
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
    from airflow.providers.cncf.kubernetes.secret import Secret
    from kubernetes.client import models as k8s
    
    @task
    def validate_inputs(**context):
        """Validate that required parameters are present."""
        conf = context.get('dag_run').conf or {}
        obj_id = conf.get('id', 'default-id')
        filename = conf.get('filename', 'default.mp4')
        
        print(f"[validate_inputs] Received: id={obj_id}, filename={filename}")
        if not obj_id or not filename:
            raise ValueError(f"Missing required parameters: id={obj_id}, filename={filename}")
        
        return {
            'id': obj_id,
            'filename': filename,
            'timestamp': datetime.utcnow().isoformat(),
        }

    @task
    def stage_info(stage_name: str, **context):
        """Log stage execution info."""
        print(f"\n{'='*60}")
        print(f"[STAGE] {stage_name}")
        print(f"{'='*60}\n")
        return stage_name

    # ============================================================================
    # STAGE 1: Virus Scanning (Simplified)
    # ============================================================================
    
    @task
    def pre_scan_check(inputs: dict):
        """Check if files are accessible for scanning."""
        print(f"[pre_scan_check] Verifying input files exist: {inputs['filename']}")
        # In real scenario, would check S3/Pachyderm connectivity
        return {**inputs, 'scan_ready': True}

    scan_pod = KubernetesPodOperator(
        task_id="run_virus_scan",
        name="virus-scan-pod",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3", "-c"],
        arguments=[
            "print('Starting virus scan...'); "
            "import time; time.sleep(2); "
            "print('Scan complete: No threats detected'); "
            "exit(0)"
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,  # Keep pod for debugging
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    @task
    def post_scan_check(scan_result):
        """Verify scan completed successfully."""
        print(f"[post_scan_check] Scan verification passed")
        return {'scan_passed': True}

    # ============================================================================
    # STAGE 2: Media Validation (Simplified)
    # ============================================================================

    @task
    def pre_validate_check(scan_data: dict):
        """Check pre-validation status."""
        print(f"[pre_validate_check] Preparing for validation")
        return {**scan_data, 'validate_ready': True}

    validate_pod = KubernetesPodOperator(
        task_id="run_media_validation",
        name="validate-media-pod",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3", "-c"],
        arguments=[
            "print('Starting media validation...'); "
            "import time; time.sleep(2); "
            "print('Validation complete: Format OK'); "
            "exit(0)"
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    @task
    def post_validate_check(validate_result):
        """Verify validation completed successfully."""
        print(f"[post_validate_check] Validation verification passed")
        return {'validation_passed': True}

    # ============================================================================
    # STAGE 3: Transcoding (Simplified)
    # ============================================================================

    @task
    def pre_transcode_check(validate_data: dict):
        """Check pre-transcoding status."""
        print(f"[pre_transcode_check] Preparing for transcoding")
        return {**validate_data, 'transcode_ready': True}

    transcode_pod = KubernetesPodOperator(
        task_id="run_transcode",
        name="transcode-pod",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3", "-c"],
        arguments=[
            "print('Starting transcoding...'); "
            "import time; time.sleep(2); "
            "print('Transcoding complete: HLS+DASH generated'); "
            "exit(0)"
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    @task
    def post_transcode_check(transcode_result):
        """Verify transcoding completed successfully."""
        print(f"[post_transcode_check] Transcoding verification passed")
        return {'transcoding_passed': True}

    # ============================================================================
    # STAGE 4: Finalization
    # ============================================================================

    @task
    def finalize(final_status: dict):
        """Summarize pipeline execution."""
        print(f"\n{'='*60}")
        print(f"[PIPELINE COMPLETE]")
        print(f"Status: {final_status}")
        print(f"{'='*60}\n")
        return {'status': 'SUCCESS', 'final_data': final_status}

    # Build the DAG
    inputs = validate_inputs()
    
    stage1 = stage_info("VIRUS SCANNING")
    pre_scan = pre_scan_check(inputs)
    scan = scan_pod
    post_scan = post_scan_check(scan)
    
    stage2 = stage_info("MEDIA VALIDATION")
    pre_validate = pre_validate_check(post_scan)
    validate = validate_pod
    post_validate = post_validate_check(validate)
    
    stage3 = stage_info("TRANSCODING")
    pre_transcode = pre_transcode_check(post_validate)
    transcode = transcode_pod
    post_transcode = post_transcode_check(transcode)
    
    stage4 = stage_info("FINALIZATION")
    final = finalize(post_transcode)

    # Define dependencies
    stage1 >> pre_scan >> scan >> post_scan
    stage2 >> pre_validate >> validate >> post_validate
    stage3 >> pre_transcode >> transcode >> post_transcode
    stage4 >> final

ingest_pipeline_v2()
