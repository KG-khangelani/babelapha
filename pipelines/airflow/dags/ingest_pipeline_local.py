"""
Local Airflow runbook DAG.

This DAG executes the ingestion flow directly in the Airflow process (no Kubernetes
pod operator) so the full repo can be started with Docker Compose and manually
triggered from the local Airflow UI/CLI.
"""

from datetime import datetime
import os
import json
import subprocess
from pathlib import Path

from airflow.sdk import dag, task, get_current_context

from provenance import (
    artifact_from_file,
    assert_success_manifests,
    provenance_failure_callback,
    provenance_retry_callback,
    provenance_success_callback,
    required_upstream_task_ids,
    s3_artifact_from_file,
    upload_file_artifact,
)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "pachyderm")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "pachyderm-secret-key-123456789")
S3_BUCKET = os.environ.get("S3_BUCKET", "pachyderm")

WORK_DIR = Path("/tmp/babelapha")
default_args = {
    "retries": 1,
    "on_success_callback": provenance_success_callback,
    "on_failure_callback": provenance_failure_callback,
    "on_retry_callback": provenance_retry_callback,
}


def run_cmd(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a command with Airflow-friendly logging and raise on non-zero exit."""
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = MINIO_ACCESS_KEY
    env["AWS_SECRET_ACCESS_KEY"] = MINIO_SECRET_KEY
    env["AWS_DEFAULT_REGION"] = "us-east-1"

    print(f"[CMD] {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({cmd[0]}): {result.stderr.strip()}")

    return result


def s3_uri(key: str) -> str:
    return f"s3://{S3_BUCKET}/{key.lstrip('/')}"


def put_report(inputs: dict, stage: str, payload: dict) -> None:
    """Upload a JSON stage report to MinIO for observability."""
    report_key = f"reports/{inputs['object_id']}/{stage}.json"
    report_path = Path("/tmp") / f"{inputs['object_id']}_{stage}_report.json"
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(
        [
            "aws",
            "--endpoint-url",
            inputs["minio_endpoint"],
            "s3",
            "cp",
            str(report_path),
            s3_uri(report_key),
        ]
    )


@dag(
    dag_id="ingest_pipeline_local",
    description="Local, Kubernetes-free ingestion pipeline for development",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=4,
    tags=["ingest", "local", "media"],
)
def ingest_pipeline_local():
    """Run the media ingestion pipeline locally against MinIO."""

    @task(retries=0)
    def validate_inputs() -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dag_run.conf or {} if dag_run else {}

        object_id = conf.get("id", "").strip()
        filename = conf.get("filename", "").strip()

        if not object_id or not filename:
            raise ValueError(f"Missing required parameters: id={object_id}, filename={filename}")

        pachyderm_commit = str(conf.get("pachyderm_commit", "")).strip() or None
        return {
            "object_id": object_id,
            "filename": filename,
            "pachyderm_commit": pachyderm_commit,
            "s3_bucket": S3_BUCKET,
            "s3_input_key": f"incoming/{object_id}/{filename}",
            "s3_output_key": f"output/{object_id}",
            "work_dir": str(WORK_DIR / object_id),
            "minio_endpoint": MINIO_ENDPOINT,
            "ts": datetime.utcnow().isoformat() + "Z",
            "provenance_stage": "request_validated",
            "provenance_decision": {
                "outcome": "accepted",
                "reason_code": "INPUT_PARAMETERS_ACCEPTED",
                "message": "The object identifier and filename are present.",
            },
        }

    @task
    def download_from_minio(inputs: dict) -> dict:
        work_dir = Path(inputs["work_dir"])
        input_dir = work_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        local_path = input_dir / inputs["filename"]
        run_cmd(
            [
                "aws",
                "--endpoint-url",
                inputs["minio_endpoint"],
                "s3",
                "cp",
                s3_uri(inputs["s3_input_key"]),
                str(local_path),
            ]
        )

        if not local_path.exists():
            raise FileNotFoundError(f"Downloaded input file not found: {local_path}")

        inputs["local_input_path"] = str(local_path)
        context = get_current_context()
        dag_run = context.get("dag_run")
        pachyderm_commit = (getattr(dag_run, "conf", {}) or {}).get("pachyderm_commit")
        remote_artifact = s3_artifact_from_file(
            local_path,
            bucket=inputs["s3_bucket"],
            key=inputs["s3_input_key"],
            endpoint_url=inputs["minio_endpoint"],
            pachyderm_commit=pachyderm_commit,
        )
        local_artifact = artifact_from_file(local_path)
        inputs["source_artifact"] = remote_artifact
        inputs["provenance_stage"] = "uploaded"
        inputs["provenance_inputs"] = [remote_artifact]
        inputs["provenance_outputs"] = [local_artifact]
        inputs["provenance_decision"] = {
            "outcome": "available",
            "reason_code": "SOURCE_DOWNLOADED_AND_HASHED",
            "message": "The uploaded source was downloaded and its SHA-256 was verified.",
        }
        return inputs

    @task
    def virus_scan(inputs: dict) -> dict:
        local_path = Path(inputs["local_input_path"])
        report = {
            "object_id": inputs["object_id"],
            "filename": inputs["filename"],
            "stage": "virus_scan",
            "status": "clean",
            "ts": datetime.utcnow().isoformat() + "Z",
        }

        print(f"[virus_scan] Quick local placeholder scan for {local_path}")
        print(json.dumps(report, indent=2))
        put_report(inputs, "virus_scan", report)
        source = inputs["source_artifact"]
        inputs["provenance_stage"] = "virus_scan"
        inputs["provenance_inputs"] = [source]
        inputs["provenance_outputs"] = [source]
        inputs["provenance_decision"] = {
            "outcome": "clean",
            "reason_code": "LOCAL_PLACEHOLDER_SCAN_CLEAN",
            "message": "Local development placeholder reported the source as clean; this is not a production ClamAV verdict.",
        }
        return inputs

    @task
    def validate_media(inputs: dict) -> dict:
        local_path = Path(inputs["local_input_path"])
        run_cmd(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                str(local_path),
            ]
        )

        put_report(
            inputs,
            "validate_media",
            {
                "object_id": inputs["object_id"],
                "filename": inputs["filename"],
                "stage": "validate_media",
                "status": "valid",
                "ts": datetime.utcnow().isoformat() + "Z",
            },
        )
        inputs["media_valid"] = True
        source = inputs["source_artifact"]
        inputs["provenance_stage"] = "validated"
        inputs["provenance_inputs"] = [source]
        inputs["provenance_outputs"] = [source]
        inputs["provenance_decision"] = {
            "outcome": "valid",
            "reason_code": "FFPROBE_ACCEPTED_MEDIA",
            "message": "FFprobe parsed the media streams and format successfully.",
        }
        return inputs

    @task
    def transcode(inputs: dict) -> dict:
        local_path = Path(inputs["local_input_path"])
        output_dir = Path(inputs["work_dir"]) / "output"
        hls_dir = output_dir / "hls"
        dash_dir = output_dir / "dash"
        hls_dir.mkdir(parents=True, exist_ok=True)
        dash_dir.mkdir(parents=True, exist_ok=True)

        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(local_path),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-f",
                "hls",
                "-hls_time",
                "10",
                "-hls_list_size",
                "0",
                str(hls_dir / "playlist.m3u8"),
            ]
        )

        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(local_path),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-f",
                "dash",
                "-seg_duration",
                "10",
                str(dash_dir / "manifest.mpd"),
            ]
        )

        inputs["hls_files"] = sorted(str(p) for p in hls_dir.glob("*") if p.is_file())
        inputs["dash_files"] = sorted(str(p) for p in dash_dir.glob("*") if p.is_file())
        output_artifacts = [artifact_from_file(path) for path in inputs["hls_files"] + inputs["dash_files"]]
        put_report(
            inputs,
            "transcode",
            {
                "object_id": inputs["object_id"],
                "filename": inputs["filename"],
                "stage": "transcode",
                "status": "success" if inputs["hls_files"] or inputs["dash_files"] else "failed",
                "hls_count": len(inputs["hls_files"]),
                "dash_count": len(inputs["dash_files"]),
                "ts": datetime.utcnow().isoformat() + "Z",
            },
        )
        inputs["provenance_stage"] = "transcoded"
        inputs["provenance_inputs"] = [inputs["source_artifact"]]
        inputs["provenance_outputs"] = output_artifacts
        inputs["provenance_decision"] = {
            "outcome": "created",
            "reason_code": "HLS_AND_DASH_CREATED",
            "message": "HLS and DASH renditions were created and hashed.",
        }
        return inputs

    @task
    def upload_results(inputs: dict) -> dict:
        output_prefix = inputs["s3_output_key"]
        output_files = list(inputs.get("hls_files", [])) + list(inputs.get("dash_files", []))
        if not output_files:
            raise RuntimeError("No output files found to upload")

        context = get_current_context()
        dag_run = context.get("dag_run")
        pachyderm_commit = (getattr(dag_run, "conf", {}) or {}).get("pachyderm_commit")
        stored_artifacts = []
        for local_file in output_files:
            local_file = Path(local_file)
            relative = local_file.relative_to(Path(inputs["work_dir"]) / "output")
            s3_key = f"{output_prefix}/{relative.as_posix()}"
            stored_artifacts.append(
                upload_file_artifact(
                    local_file,
                    bucket=inputs["s3_bucket"],
                    key=s3_key,
                    endpoint_url=inputs["minio_endpoint"],
                    pachyderm_commit=pachyderm_commit,
                )
            )

        inputs["status"] = "success"
        inputs["stored_artifacts"] = stored_artifacts
        inputs["provenance_stage"] = "published"
        inputs["provenance_inputs"] = [artifact_from_file(path) for path in output_files]
        inputs["provenance_outputs"] = stored_artifacts
        inputs["provenance_decision"] = {
            "outcome": "published",
            "reason_code": "OUTPUTS_STORED_WITH_SHA256",
            "message": "All renditions were uploaded with SHA-256 metadata.",
        }
        return inputs

    @task
    def mark_complete(inputs: dict) -> dict:
        result = {
            "status": inputs.get("status", "success"),
            "object_id": inputs["object_id"],
            "filename": inputs["filename"],
            "s3_output_key": inputs["s3_output_key"],
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "provenance_stage": "pipeline_complete",
            "provenance_inputs": inputs.get("stored_artifacts", []),
            "provenance_outputs": inputs.get("stored_artifacts", []),
            "provenance_decision": {
                "outcome": "complete",
                "reason_code": "PIPELINE_COMPLETED",
                "message": "All required ingestion stages completed successfully.",
            },
        }
        print(json.dumps(result, indent=2))
        return result

    @task
    def verify_provenance(inputs: dict) -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        locations = assert_success_manifests(
            object_id=inputs["object_id"],
            run_id=dag_run.run_id,
            task_ids=required_upstream_task_ids("ingest_pipeline_local"),
            endpoint_url=MINIO_ENDPOINT,
            bucket=S3_BUCKET,
        )
        inputs["provenance_stage"] = "provenance_verified"
        inputs["provenance_decision"] = {
            "outcome": "verified",
            "reason_code": "PROVENANCE_RECORDS_COMPLETE",
            "message": f"Verified {len(locations)} immutable manifest/OpenLineage pairs.",
        }
        return inputs

    validated = validate_inputs()
    downloaded = download_from_minio(validated)
    scanned = virus_scan(downloaded)
    validated_media = validate_media(scanned)
    transcoded = transcode(validated_media)
    uploaded = upload_results(transcoded)
    completed = mark_complete(uploaded)
    verify_provenance(completed)


ingest_pipeline_local()
