"""Production media ingestion with artifact-level provenance.

Every task attempt is recorded by the callbacks in ``provenance.py``. Processing
pods download their own source and upload their own outputs; no stage assumes
that another Kubernetes pod's ephemeral filesystem is shared.
"""

from __future__ import annotations

import hashlib
import os

from airflow.sdk import dag, get_current_context, task

from provenance import (
    artifact,
    assert_success_manifests,
    provenance_failure_callback,
    provenance_retry_callback,
    provenance_success_callback,
)


MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio.minio-tenant.svc.cluster.local:80")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "pachyderm")
PROVENANCE_S3_ENDPOINT = os.environ.get("PROVENANCE_S3_ENDPOINT", MINIO_ENDPOINT)
PROVENANCE_S3_BUCKET = os.environ.get("PROVENANCE_S3_BUCKET", S3_BUCKET)

SCAN_IMAGE = os.environ.get("BABELAPHA_SCAN_IMAGE", "localhost/clamav:latest")
VALIDATE_IMAGE = os.environ.get("BABELAPHA_VALIDATE_IMAGE", "localhost/validate:latest")
TRANSCODE_IMAGE = os.environ.get("BABELAPHA_TRANSCODE_IMAGE", "localhost/transcode:latest")

default_args = {
    "retries": 1,
    "on_success_callback": provenance_success_callback,
    "on_failure_callback": provenance_failure_callback,
    "on_retry_callback": provenance_retry_callback,
}


def _create_kpo_task(task_id, image, cmd_script, env_vars, name_prefix="task", startup_timeout_seconds=300):
    """Create a self-contained processing pod inside an active DAG context."""
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

    return KubernetesPodOperator(
        task_id=task_id,
        name=f"{name_prefix}-{task_id}",
        namespace="airflow",
        image=image,
        image_pull_policy="Always",
        cmds=["sh"],
        arguments=["-c", cmd_script],
        env_vars=env_vars,
        in_cluster=True,
        get_logs=True,
        do_xcom_push=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
        startup_timeout_seconds=startup_timeout_seconds,
    )


def _processing_env() -> dict[str, str]:
    """Templated, per-run environment shared by the processing pods."""
    return {
        "OBJECT_ID": "{{ task_instance.xcom_pull(task_ids='inspect_source')['object_id'] }}",
        "FILENAME": "{{ task_instance.xcom_pull(task_ids='inspect_source')['filename'] }}",
        "S3_BUCKET": "{{ task_instance.xcom_pull(task_ids='inspect_source')['s3_bucket'] }}",
        "S3_INPUT_KEY": "{{ task_instance.xcom_pull(task_ids='inspect_source')['s3_input_key'] }}",
        "S3_OUTPUT_KEY": "{{ task_instance.xcom_pull(task_ids='inspect_source')['s3_output_key'] }}",
        "SOURCE_SHA256": "{{ task_instance.xcom_pull(task_ids='inspect_source')['source_artifact']['sha256'] }}",
        "SOURCE_SIZE": "{{ task_instance.xcom_pull(task_ids='inspect_source')['source_artifact']['size_bytes'] }}",
        "SOURCE_VERSION_ID": "{{ task_instance.xcom_pull(task_ids='inspect_source')['source_artifact']['version']['s3_version_id'] or '' }}",
        "SOURCE_ETAG": "{{ task_instance.xcom_pull(task_ids='inspect_source')['source_artifact']['version']['etag'] or '' }}",
        "PACHYDERM_COMMIT_ID": "{{ dag_run.conf.get('pachyderm_commit', '') }}",
        "MINIO_ENDPOINT": MINIO_ENDPOINT,
        "AWS_ACCESS_KEY_ID": MINIO_ACCESS_KEY,
        "AWS_SECRET_ACCESS_KEY": MINIO_SECRET_KEY,
        "AWS_DEFAULT_REGION": "us-east-1",
    }


SOURCE_XCOM = r"""
import json, os
source = {
    "uri": f"s3://{os.environ['S3_BUCKET']}/{os.environ['S3_INPUT_KEY']}",
    "kind": "OBJECT",
    "sha256": os.environ["SOURCE_SHA256"],
    "size_bytes": int(os.environ["SOURCE_SIZE"]),
    "media_type": None,
    "integrity": "VERIFIED",
    "version": {
        "pachyderm_commit": os.environ.get("PACHYDERM_COMMIT_ID") or None,
        "s3_version_id": os.environ.get("SOURCE_VERSION_ID") or None,
        "etag": os.environ.get("SOURCE_ETAG") or None,
    },
}
"""


@dag(
    dag_id="ingest_pipeline",
    description="Media ingestion pipeline with immutable provenance and OpenLineage",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "pachyderm", "media", "production", "openlineage"],
)
def ingest_pipeline():
    @task(retries=0)
    def validate_inputs() -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dag_run.conf or {} if dag_run else {}
        object_id = str(conf.get("id", "")).strip()
        filename = str(conf.get("filename", "")).strip()
        if not object_id or not filename:
            raise ValueError(f"Missing required parameters: id={object_id}, filename={filename}")
        if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
            raise RuntimeError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be injected by the deployment")
        input_key = f"incoming/{object_id}/{filename}"
        pachyderm_commit = str(conf.get("pachyderm_commit", "")).strip() or None
        return {
            "object_id": object_id,
            "filename": filename,
            "pachyderm_commit": pachyderm_commit,
            "s3_bucket": S3_BUCKET,
            "s3_input_key": input_key,
            "s3_output_key": f"output/{object_id}",
            "provenance_stage": "request_validated",
            "provenance_inputs": [
                artifact(
                    f"s3://{S3_BUCKET}/{input_key}",
                    pachyderm_commit=pachyderm_commit,
                )
            ],
            "provenance_decision": {
                "outcome": "accepted",
                "reason_code": "INPUT_PARAMETERS_ACCEPTED",
                "message": "The object identifier and filename are present.",
            },
        }

    @task
    def inspect_source(inputs: dict) -> dict:
        """Stream the source once to establish its exact storage and content identity."""
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
        )
        response = client.get_object(Bucket=inputs["s3_bucket"], Key=inputs["s3_input_key"])
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: response["Body"].read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        source = artifact(
            f"s3://{inputs['s3_bucket']}/{inputs['s3_input_key']}",
            sha256=digest.hexdigest(),
            size_bytes=size,
            media_type=response.get("ContentType"),
            pachyderm_commit=(getattr(get_current_context().get("dag_run"), "conf", {}) or {}).get("pachyderm_commit"),
            s3_version_id=response.get("VersionId"),
            etag=response.get("ETag"),
        )
        claimed = response.get("Metadata", {}).get("sha256")
        if claimed and claimed != source["sha256"]:
            raise ValueError("Stored source SHA-256 metadata does not match the object bytes")
        inputs["source_artifact"] = source
        inputs["provenance_stage"] = "uploaded"
        inputs["provenance_inputs"] = [source]
        inputs["provenance_outputs"] = [source]
        inputs["provenance_decision"] = {
            "outcome": "verified",
            "reason_code": "SOURCE_SHA256_VERIFIED",
            "message": "The complete source object was read and its SHA-256 was verified.",
        }
        return inputs

    source = inspect_source(validate_inputs())
    pod_env = _processing_env()

    virus_scan = _create_kpo_task(
        task_id="virus_scan",
        image=SCAN_IMAGE,
        name_prefix="scan",
        startup_timeout_seconds=300,
        env_vars=pod_env,
        cmd_script=r"""
set -eu
mkdir -p /work /airflow/xcom
aws --endpoint-url "$MINIO_ENDPOINT" s3 cp "s3://$S3_BUCKET/$S3_INPUT_KEY" /work/input
ACTUAL_SHA=$(sha256sum /work/input | awk '{print $1}')
[ "$ACTUAL_SHA" = "$SOURCE_SHA256" ] || { echo "Source SHA-256 changed before scan" >&2; exit 12; }
freshclam || echo "[virus_scan] Virus definitions could not be refreshed; using the image database"
set +e
clamscan --stdout /work/input
SCAN_EXIT=$?
set -e
if [ "$SCAN_EXIT" -eq 1 ]; then
  echo "[virus_scan] Malware detected" >&2
  exit 10
fi
[ "$SCAN_EXIT" -eq 0 ] || { echo "[virus_scan] ClamAV error: $SCAN_EXIT" >&2; exit 11; }
python3 - <<'PY'
""" + SOURCE_XCOM + r"""
payload = {
    "object_id": os.environ["OBJECT_ID"], "filename": os.environ["FILENAME"],
    "s3_bucket": os.environ["S3_BUCKET"], "s3_input_key": os.environ["S3_INPUT_KEY"],
    "s3_output_key": os.environ["S3_OUTPUT_KEY"], "source_artifact": source,
    "provenance_stage": "virus_scan", "provenance_inputs": [source], "provenance_outputs": [source],
    "provenance_decision": {"outcome": "clean", "reason_code": "CLAMAV_SCAN_CLEAN", "message": "ClamAV found no malware."},
}
json.dump(payload, open("/airflow/xcom/return.json", "w"))
PY
""",
    )

    validate_media = _create_kpo_task(
        task_id="validate_media",
        image=VALIDATE_IMAGE,
        name_prefix="validate",
        env_vars=pod_env,
        cmd_script=r"""
set -eu
mkdir -p /work /airflow/xcom
aws --endpoint-url "$MINIO_ENDPOINT" s3 cp "s3://$S3_BUCKET/$S3_INPUT_KEY" /work/input
ACTUAL_SHA=$(sha256sum /work/input | awk '{print $1}')
[ "$ACTUAL_SHA" = "$SOURCE_SHA256" ] || { echo "Source SHA-256 changed before validation" >&2; exit 12; }
ffprobe -v error -show_streams -show_format /work/input >/work/ffprobe.json
python3 - <<'PY'
""" + SOURCE_XCOM + r"""
payload = {
    "object_id": os.environ["OBJECT_ID"], "filename": os.environ["FILENAME"],
    "s3_bucket": os.environ["S3_BUCKET"], "s3_input_key": os.environ["S3_INPUT_KEY"],
    "s3_output_key": os.environ["S3_OUTPUT_KEY"], "source_artifact": source,
    "provenance_stage": "validated", "provenance_inputs": [source], "provenance_outputs": [source],
    "provenance_decision": {"outcome": "valid", "reason_code": "FFPROBE_ACCEPTED_MEDIA", "message": "FFprobe parsed the media streams and format successfully."},
}
json.dump(payload, open("/airflow/xcom/return.json", "w"))
PY
""",
    )

    transcode = _create_kpo_task(
        task_id="transcode",
        image=TRANSCODE_IMAGE,
        name_prefix="transcode",
        env_vars=pod_env,
        cmd_script=r"""
set -eu
mkdir -p "/work/output/hls" "/work/output/dash" /airflow/xcom
aws --endpoint-url "$MINIO_ENDPOINT" s3 cp "s3://$S3_BUCKET/$S3_INPUT_KEY" /work/input
ACTUAL_SHA=$(sha256sum /work/input | awk '{print $1}')
[ "$ACTUAL_SHA" = "$SOURCE_SHA256" ] || { echo "Source SHA-256 changed before transcode" >&2; exit 12; }
ffmpeg -y -i /work/input -c:v libx264 -c:a aac -f hls -hls_time 10 -hls_list_size 0 /work/output/hls/playlist.m3u8
ffmpeg -y -i /work/input -c:v libx264 -c:a aac -f dash -seg_duration 10 /work/output/dash/manifest.mpd
find /work/output -type f | while read -r FILE; do
  RELATIVE=${FILE#/work/output/}
  HASH=$(sha256sum "$FILE" | awk '{print $1}')
  aws --endpoint-url "$MINIO_ENDPOINT" s3 cp "$FILE" "s3://$S3_BUCKET/$S3_OUTPUT_KEY/$RELATIVE" --metadata "sha256=$HASH"
done
python3 - <<'PY'
""" + SOURCE_XCOM + r"""
import glob, hashlib
outputs = []
for path in sorted(glob.glob("/work/output/**/*", recursive=True)):
    if not os.path.isfile(path):
        continue
    relative = os.path.relpath(path, "/work/output").replace(os.sep, "/")
    with open(path, "rb") as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    outputs.append({
        "uri": f"s3://{os.environ['S3_BUCKET']}/{os.environ['S3_OUTPUT_KEY']}/{relative}",
        "kind": "OBJECT", "sha256": digest, "size_bytes": os.path.getsize(path),
        "media_type": None, "integrity": "VERIFIED",
        "version": {"pachyderm_commit": os.environ.get("PACHYDERM_COMMIT_ID") or None, "s3_version_id": None, "etag": None},
    })
payload = {
    "object_id": os.environ["OBJECT_ID"], "filename": os.environ["FILENAME"],
    "s3_bucket": os.environ["S3_BUCKET"], "s3_input_key": os.environ["S3_INPUT_KEY"],
    "s3_output_key": os.environ["S3_OUTPUT_KEY"], "source_artifact": source,
    "provenance_stage": "transcoded", "provenance_inputs": [source], "provenance_outputs": outputs,
    "provenance_decision": {"outcome": "created", "reason_code": "HLS_AND_DASH_CREATED", "message": "HLS and DASH renditions were created, hashed, and uploaded."},
}
json.dump(payload, open("/airflow/xcom/return.json", "w"))
PY
""",
    )

    @task
    def verify_outputs(inputs: dict) -> dict:
        """Verify every stored rendition against its SHA-256 object metadata."""
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
        )
        context = get_current_context()
        dag_run = context.get("dag_run")
        pachyderm_commit = (getattr(dag_run, "conf", {}) or {}).get("pachyderm_commit")
        outputs = []
        for expected in inputs.get("provenance_outputs", []):
            key = expected["uri"].split(f"s3://{inputs['s3_bucket']}/", 1)[1]
            stored = client.get_object(Bucket=inputs["s3_bucket"], Key=key)
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stored["Body"].read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            actual = digest.hexdigest()
            claimed = stored.get("Metadata", {}).get("sha256")
            if actual != expected["sha256"] or (claimed and claimed != actual):
                raise ValueError(f"Output integrity verification failed: {expected['uri']}")
            outputs.append(
                artifact(
                    expected["uri"],
                    sha256=actual,
                    size_bytes=size,
                    media_type=stored.get("ContentType"),
                    pachyderm_commit=pachyderm_commit,
                    s3_version_id=stored.get("VersionId"),
                    etag=stored.get("ETag"),
                )
            )
        if not outputs:
            raise RuntimeError("No transcoded outputs were available to verify")
        inputs["provenance_stage"] = "published"
        inputs["provenance_inputs"] = inputs.get("provenance_outputs", [])
        inputs["provenance_outputs"] = outputs
        inputs["provenance_decision"] = {
            "outcome": "published",
            "reason_code": "OUTPUTS_STORED_WITH_SHA256",
            "message": "Every stored rendition matched its expected SHA-256.",
        }
        return inputs

    @task
    def mark_complete(inputs: dict) -> dict:
        return {
            "object_id": inputs["object_id"],
            "filename": inputs["filename"],
            "status": "success",
            "provenance_stage": "pipeline_complete",
            "provenance_inputs": inputs["provenance_outputs"],
            "provenance_outputs": inputs["provenance_outputs"],
            "provenance_decision": {
                "outcome": "complete",
                "reason_code": "PIPELINE_COMPLETED",
                "message": "All required ingestion stages completed successfully.",
            },
        }

    @task
    def verify_provenance(inputs: dict) -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        locations = assert_success_manifests(
            object_id=inputs["object_id"],
            run_id=dag_run.run_id,
            task_ids=[
                "validate_inputs",
                "inspect_source",
                "virus_scan",
                "validate_media",
                "transcode",
                "verify_outputs",
                "mark_complete",
            ],
            endpoint_url=PROVENANCE_S3_ENDPOINT,
            bucket=PROVENANCE_S3_BUCKET,
        )
        inputs["provenance_stage"] = "provenance_verified"
        inputs["provenance_decision"] = {
            "outcome": "verified",
            "reason_code": "PROVENANCE_RECORDS_COMPLETE",
            "message": f"Verified {len(locations)} immutable manifest/OpenLineage pairs.",
        }
        return inputs

    source >> virus_scan >> validate_media >> transcode
    verified = verify_outputs(transcode.output)
    completed = mark_complete(verified)
    verify_provenance(completed)


ingest_pipeline()
