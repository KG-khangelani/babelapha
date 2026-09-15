#!/usr/bin/env python3
"""Inspect all immutable provenance records for one media object."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable


DAGS_DIR = Path(__file__).resolve().parent / "dags"
sys.path.insert(0, str(DAGS_DIR))

from provenance import (  # noqa: E402
    PIPELINE_TASK_CONTRACTS,
    _openlineage_execution_facet,
    _s3_client,
    _safe_segment,
    canonical_json_bytes,
    manifest_prefix,
    openlineage_event_key,
    validate_manifest,
    validate_openlineage_event_for_manifest,
    validate_openlineage_receipt,
)


def _object_prefix(object_id: str) -> str:
    return f"provenance/{_safe_segment(object_id)}/"


def read_records(
    *,
    object_id: str,
    run_id: str | None = None,
    endpoint_url: str | None = None,
    bucket: str = "pachyderm",
) -> list[dict]:
    """Read and validate all canonical records for an object or one run."""
    client = _s3_client(endpoint_url)
    prefix = manifest_prefix(object_id, run_id) if run_id else _object_prefix(object_id)
    records: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.endswith(".json"):
                continue
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            record = json.loads(body)
            validate_manifest(record)
            if record["object"]["id"] != object_id:
                raise ValueError(f"Object prefix contains a record for {record['object']['id']!r}: {key}")
            if run_id and record["run"]["id"] != run_id:
                raise ValueError(f"Run prefix contains a record for {record['run']['id']!r}: {key}")
            records.append(record)
    return sorted(
        records,
        key=lambda record: (
            record["run"]["id"],
            record["recorded_at"],
            record["run"]["task_id"],
            record["run"]["attempt"],
            record["run"]["status"],
        ),
    )


def _delivery_prefix(state: str, object_id: str, run_id: str | None = None) -> str:
    prefix = f"openlineage/{state}/{_safe_segment(object_id)}/"
    return prefix + f"{_safe_segment(run_id)}/" if run_id else prefix


def _list_json_keys(client, *, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []) if item["Key"].endswith(".json"))
    return sorted(keys)


def _read_json(client, *, bucket: str, key: str) -> tuple[bytes, dict]:
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        return body, json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON in s3://{bucket}/{key}") from exc


def read_openlineage_delivery_evidence(
    *,
    object_id: str,
    records: Iterable[dict],
    run_id: str | None = None,
    endpoint_url: str | None = None,
    bucket: str = "pachyderm",
) -> dict:
    """Join canonical manifests to their exact queued event and delivery receipt."""
    canonical_records = {record["manifest_id"]: record for record in records}
    client = _s3_client(endpoint_url)
    outbox_keys = _list_json_keys(
        client,
        bucket=bucket,
        prefix=_delivery_prefix("outbox", object_id, run_id),
    )
    receipt_keys = set(
        _list_json_keys(
            client,
            bucket=bucket,
            prefix=_delivery_prefix("delivered", object_id, run_id),
        )
    )
    states: dict[str, dict] = {}
    errors: list[dict] = []
    matched_receipts: set[str] = set()

    for outbox_key in outbox_keys:
        manifest_id = None
        event_sha256 = None
        receipt_key = None
        try:
            event_body, event = _read_json(client, bucket=bucket, key=outbox_key)
            if canonical_json_bytes(event) != event_body:
                raise ValueError("queued event bytes are not canonical")
            if openlineage_event_key(event, "outbox") != outbox_key:
                raise ValueError("queued event identity does not match its object key")
            facet = _openlineage_execution_facet(event)
            manifest_id = facet["manifestId"]
            outbox_uri = f"s3://{bucket}/{outbox_key}"
            event_sha256 = hashlib.sha256(event_body).hexdigest()
            receipt_key = openlineage_event_key(event, "delivered")
            if receipt_key in receipt_keys:
                matched_receipts.add(receipt_key)
            manifest = canonical_records.get(manifest_id)
            if manifest is None:
                raise ValueError(f"queued event references unknown manifest {manifest_id}")
            validate_openlineage_event_for_manifest(event, manifest)
            state = {
                "state": "PENDING",
                "integrity": "VERIFIED",
                "outbox_uri": outbox_uri,
                "event_sha256": event_sha256,
                "receipt_uri": None,
                "endpoint": None,
                "http_status": None,
                "delivered_at": None,
                "error": None,
            }
            if receipt_key in receipt_keys:
                _, receipt = _read_json(client, bucket=bucket, key=receipt_key)
                validate_openlineage_receipt(receipt, event, outbox_uri=outbox_uri)
                state.update(
                    {
                        "state": "DELIVERED",
                        "receipt_uri": f"s3://{bucket}/{receipt_key}",
                        "endpoint": receipt["endpoint"],
                        "http_status": receipt["http_status"],
                        "delivered_at": receipt["delivered_at"],
                    }
                )
            if manifest_id in states:
                raise ValueError(f"duplicate queued event for manifest {manifest_id}")
            states[manifest_id] = state
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if manifest_id in canonical_records:
                states[manifest_id] = {
                    "state": "INTEGRITY_ERROR",
                    "integrity": "FAILED",
                    "outbox_uri": f"s3://{bucket}/{outbox_key}",
                    "event_sha256": event_sha256,
                    "receipt_uri": f"s3://{bucket}/{receipt_key}" if receipt_key in receipt_keys else None,
                    "endpoint": None,
                    "http_status": None,
                    "delivered_at": None,
                    "error": error,
                }
            errors.append(
                {
                    "state": "INTEGRITY_ERROR",
                    "object_uri": f"s3://{bucket}/{outbox_key}",
                    "error": error,
                }
            )

    for receipt_key in sorted(receipt_keys - matched_receipts):
        try:
            _, receipt = _read_json(client, bucket=bucket, key=receipt_key)
            manifest_id = receipt.get("manifest_id")
            orphan = {
                "state": "ORPHANED_RECEIPT",
                "integrity": "FAILED",
                "outbox_uri": receipt.get("outbox_uri"),
                "event_sha256": receipt.get("event_sha256"),
                "receipt_uri": f"s3://{bucket}/{receipt_key}",
                "endpoint": receipt.get("endpoint"),
                "http_status": receipt.get("http_status"),
                "delivered_at": receipt.get("delivered_at"),
                "error": "delivery receipt has no matching queued event",
            }
            if manifest_id in canonical_records and manifest_id not in states:
                states[manifest_id] = orphan
            errors.append(
                {
                    "state": "ORPHANED_RECEIPT",
                    "object_uri": f"s3://{bucket}/{receipt_key}",
                    "error": orphan["error"],
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "state": "INTEGRITY_ERROR",
                    "object_uri": f"s3://{bucket}/{receipt_key}",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return {"states": states, "errors": errors}


def build_view(object_id: str, records: Iterable[dict], delivery_evidence: dict | None = None) -> dict:
    """Group validated records by Airflow run without inventing run state."""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        validate_manifest(record)
        if record["object"]["id"] != object_id:
            raise ValueError(f"Expected object {object_id!r}, got {record['object']['id']!r}")
        grouped.setdefault(record["run"]["id"], []).append(record)

    delivery_states = {} if delivery_evidence is None else delivery_evidence["states"]
    delivery_by_manifest_id = {}
    for run_records in grouped.values():
        for record in run_records:
            if delivery_evidence is None:
                state = {
                    "state": "NOT_CHECKED",
                    "integrity": "NOT_CHECKED",
                    "outbox_uri": None,
                    "event_sha256": None,
                    "receipt_uri": None,
                    "endpoint": None,
                    "http_status": None,
                    "delivered_at": None,
                    "error": None,
                }
            else:
                state = delivery_states.get(
                    record["manifest_id"],
                    {
                        "state": "MISSING_OUTBOX",
                        "integrity": "FAILED",
                        "outbox_uri": None,
                        "event_sha256": None,
                        "receipt_uri": None,
                        "endpoint": None,
                        "http_status": None,
                        "delivered_at": None,
                        "error": "canonical manifest has no matching queued OpenLineage event",
                    },
                )
            delivery_by_manifest_id[record["manifest_id"]] = state

    runs = []
    for run_id, run_records in sorted(grouped.items()):
        dag_ids = {record["run"]["dag_id"] for record in run_records}
        if len(dag_ids) != 1:
            raise ValueError(
                f"Run {run_id!r} contains records from multiple DAGs: {sorted(dag_ids)}"
            )
        dag_id = next(iter(dag_ids))
        expected_task_ids = list(PIPELINE_TASK_CONTRACTS.get(dag_id, ()))
        recorded_set = {record["run"]["task_id"] for record in run_records}
        if expected_task_ids:
            unexpected_task_ids = sorted(recorded_set - set(expected_task_ids))
            recorded_task_ids = [task_id for task_id in expected_task_ids if task_id in recorded_set]
            recorded_task_ids.extend(unexpected_task_ids)
            not_recorded_task_ids = [
                task_id for task_id in expected_task_ids if task_id not in recorded_set
            ]
        else:
            unexpected_task_ids = []
            recorded_task_ids = sorted(recorded_set)
            not_recorded_task_ids = []
        ordered = sorted(
            run_records,
            key=lambda record: (
                record["recorded_at"],
                record["run"]["task_id"],
                record["run"]["attempt"],
            ),
        )
        runs.append(
            {
                "run_id": run_id,
                "dag_id": dag_id,
                "statuses_observed": sorted({record["run"]["status"] for record in ordered}),
                "first_recorded_at": ordered[0]["recorded_at"],
                "last_recorded_at": ordered[-1]["recorded_at"],
                "task_coverage": {
                    "contract_known": bool(expected_task_ids),
                    "expected_task_ids": expected_task_ids,
                    "recorded_task_ids": recorded_task_ids,
                    "not_recorded_task_ids": not_recorded_task_ids,
                    "unexpected_task_ids": unexpected_task_ids,
                },
                "records": ordered,
            }
        )
    state_counts: dict[str, int] = {}
    for state in delivery_by_manifest_id.values():
        state_counts[state["state"]] = state_counts.get(state["state"], 0) + 1
    unmatched = {
        manifest_id: state
        for manifest_id, state in delivery_states.items()
        if manifest_id not in delivery_by_manifest_id
    }
    return {
        "object_id": object_id,
        "run_count": len(runs),
        "record_count": sum(map(len, grouped.values())),
        "openlineage_delivery": {
            "state_counts": state_counts,
            "by_manifest_id": delivery_by_manifest_id,
            "unmatched": unmatched,
            "errors": [] if delivery_evidence is None else delivery_evidence["errors"],
        },
        "runs": runs,
    }


def _value(value: object) -> str:
    return "-" if value is None or value == "" else str(value)


def _artifact_lines(label: str, artifacts: list[dict]) -> list[str]:
    lines = [f"    {label} ({len(artifacts)}):"]
    if not artifacts:
        lines.append("      (none)")
        return lines
    for item in artifacts:
        version = item["version"]
        lines.extend(
            [
                f"      {item['integrity']}  {item['uri']}",
                f"        sha256={_value(item['sha256'])}  bytes={_value(item['size_bytes'])}  media_type={_value(item['media_type'])}",
                "        "
                f"pachyderm_commit={_value(version['pachyderm_commit'])}  "
                f"s3_version={_value(version['s3_version_id'])}  etag={_value(version['etag'])}",
            ]
        )
    return lines


def render_text(view: dict) -> str:
    """Render a complete, stable, copy-friendly evidence view."""
    lines = [
        f"Object: {view['object_id']}",
        f"Runs: {view['run_count']}  Records: {view['record_count']}",
        "OpenLineage: "
        + ", ".join(
            f"{state}={count}"
            for state, count in sorted(view["openlineage_delivery"]["state_counts"].items())
        ),
    ]
    for run in view["runs"]:
        coverage = run["task_coverage"]
        coverage_denominator = (
            str(len(coverage["expected_task_ids"])) if coverage["contract_known"] else "unknown"
        )
        lines.extend(
            [
                "",
                f"Run: {run['run_id']}",
                f"DAG: {run['dag_id']}",
                f"Observed statuses: {', '.join(run['statuses_observed'])}",
                f"Evidence window: {run['first_recorded_at']} -> {run['last_recorded_at']}",
                f"Task coverage: {len(coverage['recorded_task_ids'])}/{coverage_denominator} recorded",
            ]
        )
        if coverage["not_recorded_task_ids"]:
            lines.append(
                "No immutable execution record: "
                + ", ".join(coverage["not_recorded_task_ids"])
            )
        if coverage["unexpected_task_ids"]:
            lines.append("Unexpected task records: " + ", ".join(coverage["unexpected_task_ids"]))
        for record in run["records"]:
            task = record["run"]
            decision = record["decision"]
            execution = record["execution"]
            container = execution["container"]
            delivery = view["openlineage_delivery"]["by_manifest_id"][record["manifest_id"]]
            lines.extend(
                [
                    "",
                    f"  [{task['status']}] stage={task['stage']} task={task['task_id']} attempt={task['attempt']}",
                    f"    decision={decision['reason_code']} outcome={decision['outcome']}",
                    f"    message={decision['message']}",
                    f"    timing={_value(task['started_at'])} -> {task['completed_at']} duration_ms={_value(task['duration_ms'])}",
                    f"    manifest={record['links']['manifest']}",
                ]
            )
            lines.extend(_artifact_lines("inputs", record["inputs"]))
            lines.extend(_artifact_lines("outputs", record["outputs"]))
            lines.extend(
                [
                    "    execution:",
                    f"      git={execution['git']['repository']}@{_value(execution['git']['commit'])}",
                    f"      code={execution['code']['path']} sha256={_value(execution['code']['sha256'])}",
                    "      "
                    f"container={container['image']} digest={_value(container['digest'])} "
                    f"identity={container['identity_status']}",
                    f"      airflow={_value(record['orchestrator']['version'])} log={_value(record['links']['airflow_log'])}",
                    "    openlineage:",
                    f"      state={delivery['state']} integrity={delivery['integrity']}",
                    f"      outbox={_value(delivery['outbox_uri'])} event_sha256={_value(delivery['event_sha256'])}",
                    "      "
                    f"receipt={_value(delivery['receipt_uri'])} endpoint={_value(delivery['endpoint'])} "
                    f"http={_value(delivery['http_status'])} "
                    f"delivered_at={_value(delivery['delivered_at'])}",
                ]
            )
            if delivery.get("error"):
                lines.append(f"      error={delivery['error']}")
    for error in view["openlineage_delivery"]["errors"]:
        lines.extend(
            [
                "",
                f"OpenLineage evidence error: {error['state']} {error['object_uri']}",
                f"  {error['error']}",
            ]
        )
    return "\n".join(lines) + "\n"


def delivery_exit_code(view: dict, *, require_delivered: bool = False) -> int:
    """Make integrity failures machine-detectable while allowing visible pending work."""
    delivery = view["openlineage_delivery"]
    states = {state["state"] for state in delivery["by_manifest_id"].values()}
    if delivery["errors"] or states & {"MISSING_OUTBOX", "ORPHANED_RECEIPT", "INTEGRITY_ERROR"}:
        return 3
    if require_delivered and states - {"DELIVERED"}:
        return 4
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show every immutable run and stage record for one media object.",
    )
    parser.add_argument("--object-id", required=True, help="Exact media object identifier")
    parser.add_argument("--run-id", help="Optionally restrict the view to one exact Airflow run ID")
    parser.add_argument("--bucket", default=os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm"))
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT"),
        help="S3-compatible endpoint; defaults to PROVENANCE_S3_ENDPOINT or MINIO_ENDPOINT",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--require-delivered",
        action="store_true",
        help="Return exit code 4 when any valid queued event is still pending",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records = read_records(
        object_id=args.object_id,
        run_id=args.run_id,
        endpoint_url=args.endpoint_url,
        bucket=args.bucket,
    )
    if not records:
        print(f"No provenance records found for object {args.object_id!r}", file=sys.stderr)
        return 2
    delivery_evidence = read_openlineage_delivery_evidence(
        object_id=args.object_id,
        records=records,
        run_id=args.run_id,
        endpoint_url=args.endpoint_url,
        bucket=args.bucket,
    )
    view = build_view(args.object_id, records, delivery_evidence)
    if args.format == "json":
        print(json.dumps(view, indent=2, sort_keys=True))
    else:
        print(render_text(view), end="")
    return delivery_exit_code(view, require_delivered=args.require_delivered)


if __name__ == "__main__":
    raise SystemExit(main())
