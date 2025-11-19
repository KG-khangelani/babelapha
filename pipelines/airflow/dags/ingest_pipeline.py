"""
Media Ingestion Pipeline for Pachyderm + Airflow

This pipeline orchestrates the complete media ingestion workflow:
1. Validate inputs and extract parameters
2. Download file from Pachyderm S3 storage (MinIO)
3. Scan for viruses using ClamAV
4. Validate media format and properties
5. Transcode to standard formats (HLS + DASH)
6. Upload results back to Pachyderm and MinIO

Configuration:
- MinIO endpoint: minio.minio-tenant.svc.cluster.local:80
- MinIO credentials: From storage-user secret in minio-tenant namespace
- S3 bucket: pachyderm (for media storage)
- Deferred imports to avoid slow provider initialization
- KubernetesPodOperator with get_logs=True for visibility
- is_delete_operator_pod=False for debugging
- node_selector for amd64 architecture (transcoding requirement)
"""
from airflow.sdk import dag, task
import json
import os

# MinIO configuration
MINIO_ENDPOINT = "http://minio.minio-tenant.svc.cluster.local:80"
MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY', 'pachyderm')
MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY', 'pachyderm-secret-key-123456789')
S3_BUCKET = "pachyderm"

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
            # MinIO paths (S3-compatible storage)
            's3_bucket': S3_BUCKET,
            's3_input_path': f"{S3_BUCKET}/input/{object_id}/{filename}",
            's3_output_path': f"{S3_BUCKET}/output/{object_id}",
            # Local paths for processing
            'local_input_path': f"/tmp/input/{filename}",
            'local_work_dir': f"/tmp/work/{object_id}",
            'output_dir': f"/tmp/output/{object_id}",
            # MinIO configuration
            'minio_endpoint': MINIO_ENDPOINT,
            'minio_access_key': MINIO_ACCESS_KEY,
            'minio_secret_key': MINIO_SECRET_KEY,
        }

    # ============================================================================
    # STAGE 1: Download from Pachyderm S3 (MinIO)
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
import sys
from pathlib import Path
import boto3

# Get parameters from XCom
s3_bucket = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
s3_key = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_input_path'] }}"
local_path = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_input_path'] }}"
work_dir = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_work_dir'] }}"
minio_endpoint = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
minio_access_key = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
minio_secret_key = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"

# Create directories
Path(work_dir).mkdir(parents=True, exist_ok=True)
Path(local_path).parent.mkdir(parents=True, exist_ok=True)

print(f"[download] Downloading from MinIO")
print(f"  Endpoint: {minio_endpoint}")
print(f"  Bucket: {s3_bucket}")
print(f"  Key: {s3_key}")
print(f"  Local: {local_path}")

try:
    # Connect to MinIO (S3-compatible)
    s3_client = boto3.client(
        's3',
        endpoint_url=minio_endpoint,
        aws_access_key_id=minio_access_key,
        aws_secret_access_key=minio_secret_key,
        use_ssl=False,
    )
    
    # Download file
    s3_client.download_file(s3_bucket, s3_key, local_path)
    print(f"[download] Successfully downloaded: {local_path}")
    
except Exception as e:
    print(f"[download] ERROR: {str(e)}")
    print(f"[download] Verify MinIO credentials and bucket/key exist")
    sys.exit(1)

sys.exit(0)
"""
        ],
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
import sys
from pathlib import Path
import boto3

object_id = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}"
output_dir = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['output_dir'] }}"
s3_bucket = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
s3_output_path = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_output_path'] }}"
minio_endpoint = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
minio_access_key = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
minio_secret_key = "{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"

print(f"[upload] Preparing to upload results for object_id={object_id}")
print(f"[upload] Output directory: {output_dir}")

# Verify output files exist
hls_manifest = Path(f"{output_dir}/hls/playlist.m3u8")
dash_manifest = Path(f"{output_dir}/dash/manifest.mpd")

if not (hls_manifest.exists() and dash_manifest.exists()):
    print(f"[upload] ERROR: Output files not found")
    print(f"[upload] HLS exists: {hls_manifest.exists()}")
    print(f"[upload] DASH exists: {dash_manifest.exists()}")
    sys.exit(1)

print(f"[upload] Found HLS: {hls_manifest}")
print(f"[upload] Found DASH: {dash_manifest}")

try:
    # Connect to MinIO
    s3_client = boto3.client(
        's3',
        endpoint_url=minio_endpoint,
        aws_access_key_id=minio_access_key,
        aws_secret_access_key=minio_secret_key,
        use_ssl=False,
    )
    
    # Upload HLS files
    hls_dir = Path(f"{output_dir}/hls")
    for file in hls_dir.glob("*"):
        s3_key = f"{s3_output_path}/hls/{file.name}"
        s3_client.upload_file(str(file), s3_bucket, s3_key)
        print(f"[upload] Uploaded HLS: {s3_key}")
    
    # Upload DASH files
    dash_dir = Path(f"{output_dir}/dash")
    for file in dash_dir.glob("*"):
        s3_key = f"{s3_output_path}/dash/{file.name}"
        s3_client.upload_file(str(file), s3_bucket, s3_key)
        print(f"[upload] Uploaded DASH: {s3_key}")
    
    print(f"[upload] Successfully uploaded all results to {s3_output_path}")
    sys.exit(0)
    
except Exception as e:
    print(f"[upload] ERROR uploading to S3: {str(e)}")
    sys.exit(1)
"""
        ],
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





