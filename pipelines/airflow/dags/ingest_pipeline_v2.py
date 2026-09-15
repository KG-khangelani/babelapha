"""Experimental ingestion diagnostics with the full provenance contract.

This DAG exercises the Kubernetes stage boundaries without processing media.
Every decision therefore says that it is diagnostic-only, every pod returns its
own callback payload, and the run cannot finish without validating the exact
manifest/OpenLineage pair for every preceding task.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os

from airflow.sdk import dag, get_current_context, task

from provenance import (
    artifact,
    assert_success_manifests,
    provenance_failure_callback,
    provenance_retry_callback,
    provenance_success_callback,
    require_digest_pinned_images,
    required_upstream_task_ids,
)


S3_BUCKET = os.environ.get("S3_BUCKET", "pachyderm")
PROVENANCE_S3_ENDPOINT = os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT")
PROVENANCE_S3_BUCKET = os.environ.get("PROVENANCE_S3_BUCKET", S3_BUCKET)

# Pin the diagnostic runtime so every Kubernetes callback can recover the exact
# registry digest directly from ``task.image`` without inheriting Airflow's
# unrelated runtime digest.
DIAGNOSTIC_IMAGE = os.environ.get(
    "BABELAPHA_DIAGNOSTIC_IMAGE",
    "python@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84",
)

default_args = {
    "retries": 1,
    "on_success_callback": provenance_success_callback,
    "on_failure_callback": provenance_failure_callback,
    "on_retry_callback": provenance_retry_callback,
}


def _diagnostic_payload(
    inputs: dict,
    *,
    stage: str,
    reason_code: str,
    message: str,
) -> dict:
    """Carry object identity while making the non-media result explicit."""
    return {
        **inputs,
        "provenance_stage": stage,
        "provenance_inputs": inputs.get("provenance_inputs", []),
        "provenance_outputs": [],
        "provenance_decision": {
            "outcome": "diagnostic_only",
            "reason_code": reason_code,
            "message": message,
        },
    }


def _pod_script(*, stage: str, reason_code: str, message: str) -> str:
    """Return a pod script that writes an honest Airflow XCom payload."""
    return f"""
import json
import os
import time

time.sleep(2)
payload = {{
    "object_id": os.environ["OBJECT_ID"],
    "filename": os.environ["FILENAME"],
    "provenance_stage": {stage!r},
    "provenance_inputs": [],
    "provenance_outputs": [],
    "provenance_decision": {{
        "outcome": "diagnostic_only",
        "reason_code": {reason_code!r},
        "message": {message!r},
    }},
}}
with open("/airflow/xcom/return.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
print(payload["provenance_decision"]["message"])
"""


@dag(
    dag_id="ingest_pipeline_v2",
    description="Experimental Kubernetes stage diagnostics with immutable provenance",
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=8,
    tags=["ingest", "diagnostic", "media", "v2", "openlineage"],
)
def ingest_pipeline_v2():
    """Exercise stage isolation without claiming that media was processed."""
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

    @task(retries=0)
    def validate_inputs() -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dag_run.conf or {} if dag_run else {}
        object_id = str(conf.get("id", "")).strip()
        filename = str(conf.get("filename", "")).strip()
        if not object_id or not filename:
            raise ValueError(f"Missing required parameters: id={object_id}, filename={filename}")
        require_digest_pinned_images(
            {"BABELAPHA_DIAGNOSTIC_IMAGE": DIAGNOSTIC_IMAGE}
        )

        pachyderm_commit = str(conf.get("pachyderm_commit", "")).strip() or None
        source = artifact(
            f"s3://{S3_BUCKET}/incoming/{object_id}/{filename}",
            pachyderm_commit=pachyderm_commit,
        )
        return {
            "object_id": object_id,
            "filename": filename,
            "pachyderm_commit": pachyderm_commit,
            "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "provenance_stage": "diagnostic_request_validated",
            "provenance_inputs": [source],
            "provenance_outputs": [],
            "provenance_decision": {
                "outcome": "accepted",
                "reason_code": "DIAGNOSTIC_PARAMETERS_ACCEPTED",
                "message": "The diagnostic object identifier and filename are present; media bytes were not inspected.",
            },
        }

    @task
    def pre_scan_check(inputs: dict) -> dict:
        return _diagnostic_payload(
            inputs,
            stage="diagnostic_virus_scan_precheck",
            reason_code="DIAGNOSTIC_SCAN_BOUNDARY_READY",
            message="The virus-scan pod boundary is ready; no media bytes were inspected.",
        )

    @task
    def post_scan_check(scan_result: dict) -> dict:
        return _diagnostic_payload(
            scan_result,
            stage="diagnostic_virus_scan_postcheck",
            reason_code="DIAGNOSTIC_SCAN_BOUNDARY_COMPLETED",
            message="The virus-scan diagnostic pod completed; no malware verdict was produced.",
        )

    @task
    def pre_validate_check(scan_data: dict) -> dict:
        return _diagnostic_payload(
            scan_data,
            stage="diagnostic_media_validation_precheck",
            reason_code="DIAGNOSTIC_VALIDATION_BOUNDARY_READY",
            message="The media-validation pod boundary is ready; no media bytes were inspected.",
        )

    @task
    def post_validate_check(validate_result: dict) -> dict:
        return _diagnostic_payload(
            validate_result,
            stage="diagnostic_media_validation_postcheck",
            reason_code="DIAGNOSTIC_VALIDATION_BOUNDARY_COMPLETED",
            message="The media-validation diagnostic pod completed; no format verdict was produced.",
        )

    @task
    def pre_transcode_check(validate_data: dict) -> dict:
        return _diagnostic_payload(
            validate_data,
            stage="diagnostic_transcode_precheck",
            reason_code="DIAGNOSTIC_TRANSCODE_BOUNDARY_READY",
            message="The transcode pod boundary is ready; no media bytes were inspected.",
        )

    @task
    def post_transcode_check(transcode_result: dict) -> dict:
        return _diagnostic_payload(
            transcode_result,
            stage="diagnostic_transcode_postcheck",
            reason_code="DIAGNOSTIC_TRANSCODE_BOUNDARY_COMPLETED",
            message="The transcode diagnostic pod completed; no renditions were produced.",
        )

    @task
    def finalize(final_status: dict) -> dict:
        return _diagnostic_payload(
            final_status,
            stage="diagnostic_pipeline_complete",
            reason_code="DIAGNOSTIC_PIPELINE_COMPLETED",
            message="All experimental stage-boundary checks completed without claiming media-processing results.",
        )

    @task(retries=0)
    def verify_provenance(inputs: dict) -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        locations = assert_success_manifests(
            object_id=inputs["object_id"],
            run_id=dag_run.run_id,
            task_ids=required_upstream_task_ids("ingest_pipeline_v2"),
            endpoint_url=PROVENANCE_S3_ENDPOINT,
            bucket=PROVENANCE_S3_BUCKET,
        )
        inputs["provenance_stage"] = "provenance_verified"
        inputs["provenance_inputs"] = []
        inputs["provenance_outputs"] = []
        inputs["provenance_decision"] = {
            "outcome": "verified",
            "reason_code": "PROVENANCE_RECORDS_COMPLETE",
            "message": f"Verified {len(locations)} immutable manifest/OpenLineage pairs.",
        }
        return inputs

    pod_env = {
        "OBJECT_ID": "{{ task_instance.xcom_pull(task_ids='validate_inputs')['object_id'] }}",
        "FILENAME": "{{ task_instance.xcom_pull(task_ids='validate_inputs')['filename'] }}",
    }

    scan_pod = KubernetesPodOperator(
        task_id="run_virus_scan",
        name="virus-scan-diagnostic-pod",
        namespace="airflow",
        image=DIAGNOSTIC_IMAGE,
        image_pull_policy="IfNotPresent",
        cmds=["python3", "-c"],
        arguments=[
            _pod_script(
                stage="diagnostic_virus_scan",
                reason_code="DIAGNOSTIC_SCAN_POD_COMPLETED",
                message="The virus-scan diagnostic pod executed; no malware verdict was produced.",
            )
        ],
        env_vars=pod_env,
        in_cluster=True,
        get_logs=True,
        do_xcom_push=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    validate_pod = KubernetesPodOperator(
        task_id="run_media_validation",
        name="media-validation-diagnostic-pod",
        namespace="airflow",
        image=DIAGNOSTIC_IMAGE,
        image_pull_policy="IfNotPresent",
        cmds=["python3", "-c"],
        arguments=[
            _pod_script(
                stage="diagnostic_media_validation",
                reason_code="DIAGNOSTIC_VALIDATION_POD_COMPLETED",
                message="The media-validation diagnostic pod executed; no format verdict was produced.",
            )
        ],
        env_vars=pod_env,
        in_cluster=True,
        get_logs=True,
        do_xcom_push=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    transcode_pod = KubernetesPodOperator(
        task_id="run_transcode",
        name="transcode-diagnostic-pod",
        namespace="airflow",
        image=DIAGNOSTIC_IMAGE,
        image_pull_policy="IfNotPresent",
        cmds=["python3", "-c"],
        arguments=[
            _pod_script(
                stage="diagnostic_transcode",
                reason_code="DIAGNOSTIC_TRANSCODE_POD_COMPLETED",
                message="The transcode diagnostic pod executed; no renditions were produced.",
            )
        ],
        env_vars=pod_env,
        in_cluster=True,
        get_logs=True,
        do_xcom_push=True,
        is_delete_operator_pod=False,
        node_selector={"kubernetes.io/arch": "amd64"},
    )

    inputs = validate_inputs()
    pre_scan = pre_scan_check(inputs)
    pre_scan >> scan_pod
    post_scan = post_scan_check(scan_pod.output)

    pre_validate = pre_validate_check(post_scan)
    pre_validate >> validate_pod
    post_validate = post_validate_check(validate_pod.output)

    pre_transcode = pre_transcode_check(post_validate)
    pre_transcode >> transcode_pod
    post_transcode = post_transcode_check(transcode_pod.output)

    final = finalize(post_transcode)
    verify_provenance(final)


ingest_pipeline_v2()
