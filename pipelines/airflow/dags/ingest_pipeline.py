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
            # MinIO bucket
            's3_bucket': S3_BUCKET,
            # S3 keys (without bucket name - just the path inside bucket)
            's3_input_key': f"input/{object_id}/{filename}",
            's3_output_key': f"output/{object_id}",
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
        image="amazon/aws-cli:latest",
        image_pull_policy="Always",
        cmds=["sh"],
        arguments=[
            "-c",
            """
# Get parameters from XCom
S3_BUCKET="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
S3_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_input_key'] }}"
LOCAL_PATH="{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_input_path'] }}"
WORK_DIR="{{ task_instance.xcom_pull(task_ids='validate_inputs')['local_work_dir'] }}"
MINIO_ENDPOINT="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
MINIO_ACCESS_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
MINIO_SECRET_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"

# Create directories
mkdir -p "$WORK_DIR"
mkdir -p "$(dirname "$LOCAL_PATH")"

echo "[download] Downloading from MinIO"
echo "  Endpoint: $MINIO_ENDPOINT"
echo "  Bucket: $S3_BUCKET"
echo "  Key: $S3_KEY"
echo "  Local: $LOCAL_PATH"

# Download using AWS CLI with MinIO endpoint
export AWS_ACCESS_KEY_ID="$MINIO_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$MINIO_SECRET_KEY"

aws s3 cp "s3://$S3_BUCKET/$S3_KEY" "$LOCAL_PATH" \
    --endpoint-url="$MINIO_ENDPOINT" \
    --s3-region us-east-1 \
    --no-sign-request || {
    echo "[download] Retrying with signature..."
    aws s3 cp "s3://$S3_BUCKET/$S3_KEY" "$LOCAL_PATH" \
        --endpoint-url="$MINIO_ENDPOINT" \
        --s3-region us-east-1
}

if [ -f "$LOCAL_PATH" ]; then
    echo "[download] Successfully downloaded: $LOCAL_PATH"
    exit 0
else
    echo "[download] ERROR: Failed to download file"
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
        image="amazon/aws-cli:latest",
        image_pull_policy="Always",
        cmds=["sh"],
        arguments=[
            "-c",
            """
# Get parameters from XCom
OBJECT_ID="{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}"
OUTPUT_DIR="{{ task_instance.xcom_pull(task_ids='validate_inputs')['output_dir'] }}"
S3_BUCKET="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}"
S3_OUTPUT_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_output_key'] }}"
MINIO_ENDPOINT="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}"
MINIO_ACCESS_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}"
MINIO_SECRET_KEY="{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}"

echo "[upload] Preparing to upload results for object_id=$OBJECT_ID"
echo "[upload] Output directory: $OUTPUT_DIR"

# Verify output files exist
if [ ! -f "$OUTPUT_DIR/hls/playlist.m3u8" ] || [ ! -f "$OUTPUT_DIR/dash/manifest.mpd" ]; then
    echo "[upload] ERROR: Output files not found"
    echo "[upload] HLS exists: $([ -f "$OUTPUT_DIR/hls/playlist.m3u8" ] && echo 'true' || echo 'false')"
    echo "[upload] DASH exists: $([ -f "$OUTPUT_DIR/dash/manifest.mpd" ] && echo 'true' || echo 'false')"
    exit 1
fi

echo "[upload] Found HLS: $OUTPUT_DIR/hls/playlist.m3u8"
echo "[upload] Found DASH: $OUTPUT_DIR/dash/manifest.mpd"

# Setup AWS CLI credentials
export AWS_ACCESS_KEY_ID="$MINIO_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$MINIO_SECRET_KEY"

# Upload HLS files
echo "[upload] Uploading HLS files..."
for file in "$OUTPUT_DIR/hls"/*; do
    if [ -f "$file" ]; then
        FILENAME=$(basename "$file")
        S3_KEY="$S3_OUTPUT_KEY/hls/$FILENAME"
        aws s3 cp "$file" "s3://$S3_BUCKET/$S3_KEY" \
            --endpoint-url="$MINIO_ENDPOINT" \
            --s3-region us-east-1 || {
            echo "[upload] Failed to upload $FILENAME"
            exit 1
        }
        echo "[upload] Uploaded HLS: $S3_KEY"
    fi
done

# Upload DASH files
echo "[upload] Uploading DASH files..."
for file in "$OUTPUT_DIR/dash"/*; do
    if [ -f "$file" ]; then
        FILENAME=$(basename "$file")
        S3_KEY="$S3_OUTPUT_KEY/dash/$FILENAME"
        aws s3 cp "$file" "s3://$S3_BUCKET/$S3_KEY" \
            --endpoint-url="$MINIO_ENDPOINT" \
            --s3-region us-east-1 || {
            echo "[upload] Failed to upload $FILENAME"
            exit 1
        }
        echo "[upload] Uploaded DASH: $S3_KEY"
    fi
done

echo "[upload] Successfully uploaded all results to $S3_OUTPUT_KEY"
exit 0
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





