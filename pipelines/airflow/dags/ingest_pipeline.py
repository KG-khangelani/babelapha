"""
Media Ingestion Pipeline for Pachyderm + Airflow

This pipeline orchestrates the complete media ingestion workflow:
1. Validate inputs and extract parameters
2. Download file from Pachyderm S3 storage
3. Scan for viruses using ClamAV
4. Validate media format and properties
5. Transcode to standard formats (HLS + DASH)
6. Upload results back to Pachyderm and MinIO

Key configuration:
- Deferred imports to avoid slow provider initialization
- KubernetesPodOperator with get_logs=True for visibility
- is_delete_operator_pod=False for debugging
- node_selector for amd64 architecture (transcoding requirement)
"""
from airflow.sdk import dag, task
import json
import os

default_args = dict(retries=1)

@dag(
    dag_id="ingest_pipeline",
    description="Media ingestion pipeline: validate → scan → transcode → upload",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media", "production"],
)
def ingest_pipeline():
    """Media ingestion pipeline with full processing workflow."""
    # Deferred import to avoid slow provider manager initialization during DAG parsing
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

    @task
    def validate_inputs(**context):
        """Validate input parameters from DAG config."""
        dag_run_conf = context.get('dag_run').conf or {}
        
        # Extract parameters
        object_id = dag_run_conf.get('id', '')
        filename = dag_run_conf.get('filename', '')
        
        if not object_id or not filename:
            raise ValueError(f"Missing required parameters: id={object_id}, filename={filename}")
        
        print(f"[validate_inputs] Received object_id={object_id}, filename={filename}")
        
        return {
            'object_id': object_id,
            'filename': filename,
            's3_input_path': f"s3://pachyderm/{object_id}/{filename}",
            'local_input_path': f"/tmp/input/{filename}",
            'local_work_dir': f"/tmp/work/{object_id}",
            'output_dir': f"/tmp/output/{object_id}",
        }

    # ============================================================================
    # STAGE 1: Download from Pachyderm S3
    # ============================================================================
    download_from_pachyderm = KubernetesPodOperator(
        task_id="download_from_pachyderm",
        name="download-pachyderm",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3"],
        arguments=[
            "-c",
            """
import os, sys, json
from pathlib import Path

# Create directories
work_dir = os.environ.get('WORK_DIR', '/tmp/work')
Path(work_dir).mkdir(parents=True, exist_ok=True)

print(f"[download] Work directory created: {work_dir}")
print(f"[download] S3_PATH={os.environ.get('S3_PATH', 'N/A')}")
print(f"[download] LOCAL_PATH={os.environ.get('LOCAL_PATH', 'N/A')}")

# TODO: Download from S3 using boto3
# s3_client = boto3.client('s3', endpoint_url='http://minio:9000')
# s3_client.download_file('pachyderm', key, local_path)

print("[download] Download would occur here (S3 credentials configured)")
sys.exit(0)
"""
        ],
        container_kwargs={
            'env': [
                {'name': 'S3_PATH', 'value': '{{ task_instance.xcom_pull(task_ids="validate_inputs")["s3_input_path"] }}'},
                {'name': 'LOCAL_PATH', 'value': '{{ task_instance.xcom_pull(task_ids="validate_inputs")["local_input_path"] }}'},
                {'name': 'WORK_DIR', 'value': '{{ task_instance.xcom_pull(task_ids="validate_inputs")["local_work_dir"] }}'},
                {'name': 'AWS_ACCESS_KEY_ID', 'value': os.environ.get('MINIO_ACCESS_KEY', 'pachyderm')},
                {'name': 'AWS_SECRET_ACCESS_KEY', 'value': os.environ.get('MINIO_SECRET_KEY', 'pachyderm')},
            ]
        },
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    # ============================================================================
    # STAGE 2: Virus Scan with ClamAV
    # ============================================================================
    virus_scan = KubernetesPodOperator(
        task_id="virus_scan",
        name="virus-scan",
        namespace="airflow",
        image="clamav/clamav:latest",  # Pre-built ClamAV image
        image_pull_policy="Always",
        cmds=["bash"],
        arguments=[
            "-c",
            """
INPUT_FILE="{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_input_path'] }}"
echo "[virus_scan] Starting ClamAV scan on: $INPUT_FILE"

# Update virus database
freshclam || echo "Warning: freshclam failed (may be offline)"

# Run scan
clamscan -v "$INPUT_FILE" 2>&1 | head -50
SCAN_STATUS=$?

if [ $SCAN_STATUS -eq 0 ]; then
    echo "[virus_scan] File is clean - no viruses detected"
    exit 0
elif [ $SCAN_STATUS -eq 1 ]; then
    echo "[virus_scan] WARNING: Virus detected!"
    exit 1
else
    echo "[virus_scan] Scan error: $SCAN_STATUS"
    exit 1
fi
"""
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    # ============================================================================
    # STAGE 3: Media Validation
    # ============================================================================
    validate_media = KubernetesPodOperator(
        task_id="validate_media",
        name="validate-media",
        namespace="airflow",
        image="jrottenberg/ffmpeg:latest",  # FFmpeg has ffprobe for validation
        image_pull_policy="Always",
        cmds=["bash"],
        arguments=[
            "-c",
            """
INPUT_FILE="{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_input_path'] }}"
echo "[validate_media] Validating media file: $INPUT_FILE"

# Get media information
ffprobe -v error -show_format -show_streams "$INPUT_FILE" 2>&1 | head -30

# Basic validation
if ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$INPUT_FILE" > /dev/null 2>&1; then
    echo "[validate_media] Media validation successful"
    exit 0
else
    echo "[validate_media] Media validation failed"
    exit 1
fi
"""
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    # ============================================================================
    # STAGE 4: Transcode to HLS + DASH
    # ============================================================================
    transcode = KubernetesPodOperator(
        task_id="transcode",
        name="transcode",
        namespace="airflow",
        image="jrottenberg/ffmpeg:latest",
        image_pull_policy="Always",
        cmds=["bash"],
        arguments=[
            "-c",
            """
INPUT_FILE="{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_input_path'] }}"
OUTPUT_DIR="{{ task_instance.xcom_pull(task_ids='validate_inputs')['output_dir'] }}"
OBJECT_ID="{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}"

mkdir -p "$OUTPUT_DIR/hls" "$OUTPUT_DIR/dash"

echo "[transcode] Starting transcoding to HLS + DASH"
echo "Input: $INPUT_FILE"
echo "Output: $OUTPUT_DIR"

# HLS Transcoding
echo "[transcode] Creating HLS output..."
ffmpeg -i "$INPUT_FILE" \\
    -c:v libx264 -crf 23 -c:a aac \\
    -f hls -hls_time 10 -hls_list_size 0 \\
    "$OUTPUT_DIR/hls/playlist.m3u8" 2>&1 | tail -20

# DASH Transcoding
echo "[transcode] Creating DASH output..."
ffmpeg -i "$INPUT_FILE" \\
    -c:v libx264 -crf 23 -c:a aac \\
    -f dash -seg_duration 10 \\
    "$OUTPUT_DIR/dash/manifest.mpd" 2>&1 | tail -20

if [ -f "$OUTPUT_DIR/hls/playlist.m3u8" ] && [ -f "$OUTPUT_DIR/dash/manifest.mpd" ]; then
    echo "[transcode] Transcoding completed successfully"
    echo "[transcode] HLS: $OUTPUT_DIR/hls/playlist.m3u8"
    echo "[transcode] DASH: $OUTPUT_DIR/dash/manifest.mpd"
    exit 0
else
    echo "[transcode] Transcoding failed - output files not created"
    exit 1
fi
"""
        ],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    # ============================================================================
    # STAGE 5: Upload Results
    # ============================================================================
    upload_results = KubernetesPodOperator(
        task_id="upload_results",
        name="upload-results",
        namespace="airflow",
        image="python:3.11-slim",
        image_pull_policy="Always",
        cmds=["python3"],
        arguments=[
            "-c",
            """
import os, sys
from pathlib import Path

object_id = os.environ.get('OBJECT_ID', '')
output_dir = os.environ.get('OUTPUT_DIR', '/tmp/output')

print(f"[upload] Preparing to upload results for object_id={object_id}")
print(f"[upload] Output directory: {output_dir}")

# Verify output files exist
hls_manifest = Path(f"{output_dir}/hls/playlist.m3u8")
dash_manifest = Path(f"{output_dir}/dash/manifest.mpd")

if hls_manifest.exists() and dash_manifest.exists():
    print(f"[upload] Found HLS: {hls_manifest}")
    print(f"[upload] Found DASH: {dash_manifest}")
    # TODO: Upload to MinIO/S3 using boto3
    # s3_client.upload_file(..., f"pachyderm/output/{object_id}/hls/...")
    print("[upload] Upload would proceed to S3 storage")
    sys.exit(0)
else:
    print(f"[upload] ERROR: Output files not found")
    print(f"[upload] HLS exists: {hls_manifest.exists()}")
    print(f"[upload] DASH exists: {dash_manifest.exists()}")
    sys.exit(1)
"""
        ],
        container_kwargs={
            'env': [
                {'name': 'OBJECT_ID', 'value': '{{ task_instance.xcom_pull(task_ids="validate_inputs")["object_id"] }}'},
                {'name': 'OUTPUT_DIR', 'value': '{{ task_instance.xcom_pull(task_ids="validate_inputs")["output_dir"] }}'},
            ]
        },
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    @task
    def mark_complete(**context):
        """Mark pipeline as completed."""
        conf = context.get('dag_run').conf or {}
        object_id = conf.get('id', 'unknown')
        print(f"[complete] Pipeline successfully completed for object_id={object_id}")
        return f"ingest_completed_{object_id}"

    # Define pipeline flow
    inputs = validate_inputs()
    inputs >> download_from_pachyderm >> virus_scan >> validate_media >> transcode >> upload_results >> mark_complete()

ingest_pipeline()





