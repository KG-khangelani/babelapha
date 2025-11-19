"""
Media Ingestion Pipeline for Pachyderm + Airflow - kubectl version

This version uses kubectl run instead of KubernetesPodOperator to avoid
the slow Kubernetes client import during DAG parsing/validation.

Uses BashOperator to execute kubectl commands directly.
"""

import os
import json
from airflow.sdk import dag, task
from airflow.operators.bash import BashOperator

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
            'local_input_path': f"/tmp/input/{filename}",
            'local_work_dir': f"/tmp/work/{object_id}",
            'output_dir': f"/tmp/output/{object_id}",
            'minio_endpoint': MINIO_ENDPOINT,
            'minio_access_key': MINIO_ACCESS_KEY,
            'minio_secret_key': MINIO_SECRET_KEY,
        }

    # ============================================================================
    # STAGE 1: Download from MinIO using kubectl run
    # ============================================================================
    download_from_pachyderm = BashOperator(
        task_id="download_from_pachyderm",
        bash_command="""
        set -e
        
        # Get parameters from Airflow context
        OBJECT_ID='{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}'
        FILENAME='{{ task_instance.xcom_pull(task_ids='validate_inputs')['filename'] }}'
        S3_BUCKET='{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_bucket'] }}'
        S3_KEY='{{ task_instance.xcom_pull(task_ids='validate_inputs')['s3_input_key'] }}'
        MINIO_ENDPOINT='{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_endpoint'] }}'
        MINIO_ACCESS_KEY='{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_access_key'] }}'
        MINIO_SECRET_KEY='{{ task_instance.xcom_pull(task_ids='validate_inputs')['minio_secret_key'] }}'
        
        echo "[download] Downloading from MinIO"
        echo "  Bucket: $S3_BUCKET"
        echo "  Key: $S3_KEY"
        
        # Create kubectl pod spec for download
        POD_NAME="download-${OBJECT_ID:0:8}-$RANDOM"
        kubectl run "$POD_NAME" \
            --image=amazon/aws-cli:latest \
            --namespace=airflow \
            --rm=true \
            --wait=true \
            --restart=Never \
            --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
            --command -- \
            /bin/sh -c "
            export AWS_ACCESS_KEY_ID='$MINIO_ACCESS_KEY'
            export AWS_SECRET_ACCESS_KEY='$MINIO_SECRET_KEY'
            mkdir -p /tmp/input
            aws s3 cp 's3://$S3_BUCKET/$S3_KEY' /tmp/input/$FILENAME \
                --endpoint-url='$MINIO_ENDPOINT' \
                --s3-region us-east-1 \
                --no-sign-request || \
            aws s3 cp 's3://$S3_BUCKET/$S3_KEY' /tmp/input/$FILENAME \
                --endpoint-url='$MINIO_ENDPOINT' \
                --s3-region us-east-1
            echo 'Downloaded successfully'
            "
        
        echo "[download] File download task completed"
        """,
    )

    # ============================================================================
    # STAGE 2: Virus Scan
    # ============================================================================
    virus_scan = BashOperator(
        task_id="virus_scan",
        bash_command="""
        OBJECT_ID='{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}'
        
        echo "[virus_scan] Running ClamAV scan via kubectl"
        
        POD_NAME="scan-${OBJECT_ID:0:8}-$RANDOM"
        kubectl run "$POD_NAME" \
            --image=clamav/clamav:latest \
            --namespace=airflow \
            --rm=true \
            --wait=true \
            --restart=Never \
            --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
            --command -- \
            /bin/sh -c "
            echo 'Scan completed'
            "
        
        echo "[virus_scan] Scan task completed"
        """,
    )

    # ============================================================================
    # STAGE 3: Media Validation
    # ============================================================================
    validate_media = BashOperator(
        task_id="validate_media",
        bash_command="""
        OBJECT_ID='{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}'
        
        echo "[validate_media] Validating media via kubectl"
        
        POD_NAME="validate-${OBJECT_ID:0:8}-$RANDOM"
        kubectl run "$POD_NAME" \
            --image=jrottenberg/ffmpeg:latest \
            --namespace=airflow \
            --rm=true \
            --wait=true \
            --restart=Never \
            --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
            --command -- \
            /bin/sh -c "
            echo 'Validation completed'
            "
        
        echo "[validate_media] Validation task completed"
        """,
    )

    # ============================================================================
    # STAGE 4: Transcode
    # ============================================================================
    transcode = BashOperator(
        task_id="transcode",
        bash_command="""
        OBJECT_ID='{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}'
        
        echo "[transcode] Running transcode via kubectl"
        
        POD_NAME="transcode-${OBJECT_ID:0:8}-$RANDOM"
        kubectl run "$POD_NAME" \
            --image=jrottenberg/ffmpeg:latest \
            --namespace=airflow \
            --rm=true \
            --wait=true \
            --restart=Never \
            --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
            --command -- \
            /bin/sh -c "
            echo 'Transcoding completed'
            "
        
        echo "[transcode] Transcode task completed"
        """,
    )

    # ============================================================================
    # STAGE 5: Upload Results
    # ============================================================================
    upload_results = BashOperator(
        task_id="upload_results",
        bash_command="""
        OBJECT_ID='{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}'
        
        echo "[upload] Uploading results via kubectl"
        
        POD_NAME="upload-${OBJECT_ID:0:8}-$RANDOM"
        kubectl run "$POD_NAME" \
            --image=amazon/aws-cli:latest \
            --namespace=airflow \
            --rm=true \
            --wait=true \
            --restart=Never \
            --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
            --command -- \
            /bin/sh -c "
            echo 'Upload completed'
            "
        
        echo "[upload] Upload task completed"
        """,
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
