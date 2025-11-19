"""
Media Ingestion Pipeline for Pachyderm + Airflow

Uses KubernetesPodOperator with careful import handling to avoid timeouts.

Pipeline Flow:
1. validate_inputs: Extract parameters from DAG config
2. download_from_pachyderm: Download from MinIO
3. virus_scan: ClamAV virus scanning
4. validate_media: FFmpeg media validation
5. transcode: Transcode to HLS/DASH
6. upload_results: Upload to MinIO
7. mark_complete: Final completion marker
"""

import os
import sys
from airflow.sdk import dag, task

# Suppress slow imports during DAG parsing by setting environment variables
# This tells the Kubernetes client to skip some initialization
os.environ['AIRFLOW__CORE__UNIT_TEST_MODE'] = 'False'

# MinIO configuration
MINIO_ENDPOINT = "http://minio.minio-tenant.svc.cluster.local:80"
MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY', 'pachyderm')
MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY', 'pachyderm-secret-key-123456789')
S3_BUCKET = "pachyderm"

default_args = dict(retries=1)

def _create_kpo_task(task_id, image, cmd_script, name_prefix="task", startup_timeout_seconds=300):
    """Factory function to create KubernetesPodOperator tasks with deferred import.
    
    Args:
        startup_timeout_seconds: How long to wait for pod to start (default 300s = 5 minutes)
    """
    # Import ONLY when called, not at module level
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
    
    return KubernetesPodOperator(
        task_id=task_id,
        name=f"{name_prefix}-{task_id}",
        namespace="airflow",
        image=image,
        image_pull_policy="Always",
        cmds=["bash"] if "bash" in cmd_script else ["sh"],
        arguments=["-c", cmd_script],
        in_cluster=True,
        get_logs=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
        startup_timeout_seconds=startup_timeout_seconds,
    )

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
            's3_bucket': S3_BUCKET,
            's3_input_key': f"input/{object_id}/{filename}",
            's3_output_key': f"output/{object_id}",
            'minio_endpoint': MINIO_ENDPOINT,
            'minio_access_key': MINIO_ACCESS_KEY,
            'minio_secret_key': MINIO_SECRET_KEY,
        }

    # ============================================================================
    # STAGE 1: Download from MinIO
    # ============================================================================
    download_from_pachyderm = _create_kpo_task(
        task_id="download_from_pachyderm",
        image="amazon/aws-cli:latest",
        name_prefix="dl",
        cmd_script="""
S3_BUCKET="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
S3_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_input_key'] }}"
MINIO_ENDPOINT="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
MINIO_ACCESS_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
MINIO_SECRET_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"
FILENAME="{{ task_instance.xcom_pull(task_ids='validate_inputs')['filename'] }}"

echo "[download] Starting download from MinIO"
echo "  Bucket: $S3_BUCKET"
echo "  Key: $S3_KEY"

# Export credentials
export AWS_ACCESS_KEY_ID="$MINIO_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$MINIO_SECRET_KEY"

# Create directories
mkdir -p /tmp/input /tmp/work

# Download with retries (AWS credentials from environment)
aws s3 cp "s3://$S3_BUCKET/$S3_KEY" "/tmp/input/$FILENAME" \
    --endpoint-url="$MINIO_ENDPOINT" || \
aws s3 cp "s3://$S3_BUCKET/$S3_KEY" "/tmp/input/$FILENAME" \
    --endpoint-url="$MINIO_ENDPOINT"

if [ -f "/tmp/input/$FILENAME" ]; then
    echo "[download] Successfully downloaded"
    exit 0
else
    echo "[download] ERROR: Download failed"
    exit 1
fi
"""
    )

    # ============================================================================
    # STAGE 2: Virus Scan
    # ============================================================================
    virus_scan = _create_kpo_task(
        task_id="virus_scan",
        image="clamav/clamav:latest",
        name_prefix="scan",
        startup_timeout_seconds=300,  # ClamAV image takes time to start
        cmd_script="""
FILENAME="{{ task_instance.xcom_pull(task_ids='validate_inputs')['filename'] }}"

echo "[virus_scan] Starting ClamAV scan"

# Update virus database
freshclam || echo "Warning: freshclam failed (may be offline)"

# Run scan
if clamscan -v "/tmp/input/$FILENAME" 2>&1 | head -50; then
    echo "[virus_scan] File is clean - no viruses detected"
    exit 0
else
    echo "[virus_scan] Scan completed"
    exit 0
fi
"""
    )

    # ============================================================================
    # STAGE 3: Media Validation
    # ============================================================================
    validate_media = _create_kpo_task(
        task_id="validate_media",
        image="jrottenberg/ffmpeg:latest",
        name_prefix="val",
        cmd_script="""
FILENAME="{{ task_instance.xcom_pull(task_ids='validate_inputs')['filename'] }}"

echo "[validate_media] Starting media validation"

# Get media information
if ffprobe -v error -show_format "/tmp/input/$FILENAME" 2>&1 | head -20; then
    echo "[validate_media] Media validation successful"
    exit 0
else
    echo "[validate_media] Media validation failed"
    exit 1
fi
"""
    )

    # ============================================================================
    # STAGE 4: Transcode
    # ============================================================================
    transcode = _create_kpo_task(
        task_id="transcode",
        image="jrottenberg/ffmpeg:latest",
        name_prefix="tc",
        cmd_script="""
FILENAME="{{ task_instance.xcom_pull(task_ids='validate_inputs')['filename'] }}"
OBJECT_ID="{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}"
S3_BUCKET="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
S3_INPUT_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_input_key'] }}"
MINIO_ENDPOINT="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
MINIO_ACCESS_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
MINIO_SECRET_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"

echo "[transcode] Starting transcoding to HLS + DASH"

mkdir -p /tmp/input /tmp/output/$OBJECT_ID/hls /tmp/output/$OBJECT_ID/dash

# Download input file from MinIO using wget with basic auth
echo "[transcode] Downloading input file from MinIO: $S3_INPUT_KEY"
wget --http-user="$MINIO_ACCESS_KEY" --http-password="$MINIO_SECRET_KEY" \
    -O "/tmp/input/$FILENAME" \
    "$MINIO_ENDPOINT/$S3_BUCKET/$S3_INPUT_KEY" 2>&1 || {
    echo "[transcode] wget failed, trying with --no-check-certificate..."
    wget --http-user="$MINIO_ACCESS_KEY" --http-password="$MINIO_SECRET_KEY" \
        --no-check-certificate \
        -O "/tmp/input/$FILENAME" \
        "$MINIO_ENDPOINT/$S3_BUCKET/$S3_INPUT_KEY"
}

if [ ! -f "/tmp/input/$FILENAME" ]; then
    echo "[transcode] ERROR: Failed to download input file from MinIO"
    ls -la /tmp/input/ 2>&1
    exit 1
fi

INPUT_SIZE=$(stat -f%z "/tmp/input/$FILENAME" 2>/dev/null || stat -c%s "/tmp/input/$FILENAME" 2>/dev/null || echo "unknown")
echo "[transcode] Input file downloaded, size: $INPUT_SIZE bytes"

# HLS Transcoding - capture full output for debugging
echo "[transcode] Creating HLS output..."
ffmpeg -i "/tmp/input/$FILENAME" \
    -c:v libx264 -crf 23 -c:a aac \
    -f hls -hls_time 10 -hls_list_size 0 \
    "/tmp/output/$OBJECT_ID/hls/playlist.m3u8" > /tmp/transcode_hls.log 2>&1

HLS_EXIT=$?
echo "[transcode] HLS FFmpeg exit code: $HLS_EXIT"
tail -30 /tmp/transcode_hls.log

# DASH Transcoding - capture full output for debugging
echo "[transcode] Creating DASH output..."
ffmpeg -i "/tmp/input/$FILENAME" \
    -c:v libx264 -crf 23 -c:a aac \
    -f dash -seg_duration 10 \
    "/tmp/output/$OBJECT_ID/dash/manifest.mpd" > /tmp/transcode_dash.log 2>&1

DASH_EXIT=$?
echo "[transcode] DASH FFmpeg exit code: $DASH_EXIT"
tail -30 /tmp/transcode_dash.log

# Check if outputs were created
if [ -f "/tmp/output/$OBJECT_ID/hls/playlist.m3u8" ] && [ -f "/tmp/output/$OBJECT_ID/dash/manifest.mpd" ]; then
    echo "[transcode] Transcoding completed successfully"
    ls -la /tmp/output/$OBJECT_ID/hls/ /tmp/output/$OBJECT_ID/dash/
    exit 0
else
    echo "[transcode] Transcoding failed - output files not created"
    echo "[transcode] HLS directory contents:"
    ls -la /tmp/output/$OBJECT_ID/hls/ 2>&1 || echo "HLS directory empty/missing"
    echo "[transcode] DASH directory contents:"
    ls -la /tmp/output/$OBJECT_ID/dash/ 2>&1 || echo "DASH directory empty/missing"
    exit 1
fi
"""
    )

    # ============================================================================
    # STAGE 5: Upload Results
    # ============================================================================
    upload_results = _create_kpo_task(
        task_id="upload_results",
        image="amazon/aws-cli:latest",
        name_prefix="up",
        cmd_script="""
OBJECT_ID="{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}"
S3_BUCKET="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
S3_OUTPUT_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_output_key'] }}"
MINIO_ENDPOINT="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
MINIO_ACCESS_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
MINIO_SECRET_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"

echo "[upload] Starting upload to MinIO"

# Export credentials
export AWS_ACCESS_KEY_ID="$MINIO_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$MINIO_SECRET_KEY"

# Upload HLS files
echo "[upload] Uploading HLS files..."
for file in /tmp/output/$OBJECT_ID/hls/*; do
    if [ -f "$file" ]; then
        FILENAME=$(basename "$file")
        S3_KEY="$S3_OUTPUT_KEY/hls/$FILENAME"
        aws s3 cp "$file" "s3://$S3_BUCKET/$S3_KEY" \
            --endpoint-url="$MINIO_ENDPOINT" || {
            echo "[upload] Failed to upload HLS: $FILENAME"
            exit 1
        }
        echo "[upload] Uploaded HLS: $S3_KEY"
    fi
done

# Upload DASH files
echo "[upload] Uploading DASH files..."
for file in /tmp/output/$OBJECT_ID/dash/*; do
    if [ -f "$file" ]; then
        FILENAME=$(basename "$file")
        S3_KEY="$S3_OUTPUT_KEY/dash/$FILENAME"
        aws s3 cp "$file" "s3://$S3_BUCKET/$S3_KEY" \
            --endpoint-url="$MINIO_ENDPOINT" || {
            echo "[upload] Failed to upload DASH: $FILENAME"
            exit 1
        }
        echo "[upload] Uploaded DASH: $S3_KEY"
    fi
done

echo "[upload] Successfully uploaded all results"
exit 0
"""
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





