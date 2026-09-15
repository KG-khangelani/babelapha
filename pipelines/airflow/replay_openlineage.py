#!/usr/bin/env python3
"""Replay immutable OpenLineage outbox events that lack delivery receipts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


DAGS_DIR = Path(__file__).resolve().parent / "dags"
sys.path.insert(0, str(DAGS_DIR))

from provenance import (  # noqa: E402
    _openlineage_execution_facet,
    _openlineage_target,
    _s3_client,
    _safe_segment,
    canonical_json_bytes,
    emit_openlineage_event,
    openlineage_event_key,
    persist_openlineage_receipt,
    validate_openlineage_receipt,
)


def _prefix(state: str, object_id: str | None = None) -> str:
    prefix = f"openlineage/{state}/"
    return prefix + f"{_safe_segment(object_id)}/" if object_id else prefix


def _list_json_keys(client, *, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []) if item["Key"].endswith(".json"))
    return sorted(keys)


def _read_json_bytes(client, *, bucket: str, key: str) -> tuple[bytes, dict]:
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        record = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON in s3://{bucket}/{key}") from exc
    return body, record


def _read_queued_event(client, *, bucket: str, key: str) -> dict:
    body, event = _read_json_bytes(client, bucket=bucket, key=key)
    if canonical_json_bytes(event) != body:
        raise ValueError(f"Outbox event is not the original canonical bytes: s3://{bucket}/{key}")
    expected_key = openlineage_event_key(event, "outbox")
    if key != expected_key:
        raise ValueError(f"Outbox event identity does not match its key: s3://{bucket}/{key}")
    return event


def replay_pending(
    *,
    client,
    bucket: str,
    object_id: str | None = None,
    manifest_id: str | None = None,
    openlineage_url: str | None = None,
    timeout: float = 5.0,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Replay selected queued events, retaining a result row for every decision."""
    if limit is not None and limit < 1:
        raise ValueError("Replay limit must be a positive integer")
    target = _openlineage_target(openlineage_url)
    if not dry_run and not target:
        raise RuntimeError("OPENLINEAGE_URL is not configured or delivery is disabled")

    outbox_keys = _list_json_keys(client, bucket=bucket, prefix=_prefix("outbox", object_id))
    receipt_keys = set(_list_json_keys(client, bucket=bucket, prefix=_prefix("delivered", object_id)))
    result = {
        "bucket": bucket,
        "object_id": object_id,
        "manifest_id": manifest_id,
        "dry_run": dry_run,
        "queued_selected": 0,
        "already_delivered": 0,
        "pending_found": 0,
        "pending_remaining": 0,
        "replayed": 0,
        "failed": 0,
        "events": [],
    }

    for outbox_key in outbox_keys:
        try:
            event = _read_queued_event(client, bucket=bucket, key=outbox_key)
            facet = _openlineage_execution_facet(event)
        except Exception as exc:
            result["failed"] += 1
            result["events"].append({"outbox_key": outbox_key, "action": "invalid", "error": str(exc)})
            continue
        if manifest_id and facet["manifestId"] != manifest_id:
            continue

        result["queued_selected"] += 1
        outbox_uri = f"s3://{bucket}/{outbox_key}"
        receipt_key = openlineage_event_key(event, "delivered")
        event_result = {
            "manifest_id": facet["manifestId"],
            "object_id": facet["objectId"],
            "airflow_run_id": facet["airflowRunId"],
            "task_id": facet["taskId"],
            "attempt": facet["attempt"],
            "status": facet["status"],
            "outbox_uri": outbox_uri,
        }

        if receipt_key in receipt_keys:
            try:
                _, receipt = _read_json_bytes(client, bucket=bucket, key=receipt_key)
                validate_openlineage_receipt(receipt, event, outbox_uri=outbox_uri)
                event_result["action"] = "already_delivered"
                event_result["receipt_uri"] = f"s3://{bucket}/{receipt_key}"
                result["already_delivered"] += 1
            except Exception as exc:
                event_result["action"] = "invalid_receipt"
                event_result["error"] = str(exc)
                result["failed"] += 1
            result["events"].append(event_result)
            continue

        if limit is not None and result["pending_found"] >= limit:
            break
        result["pending_found"] += 1
        if dry_run:
            event_result["action"] = "would_replay"
            result["pending_remaining"] += 1
            result["events"].append(event_result)
            continue

        try:
            http_status = emit_openlineage_event(event, target=target, timeout=timeout)
            if http_status is None:
                raise RuntimeError("OpenLineage target disappeared before delivery")
            receipt_uri = persist_openlineage_receipt(
                event,
                outbox_uri=outbox_uri,
                openlineage_target=target,
                http_status=http_status,
                bucket=bucket,
                client=client,
            )
            event_result["action"] = "replayed"
            event_result["http_status"] = http_status
            event_result["receipt_uri"] = receipt_uri
            result["replayed"] += 1
        except Exception as exc:
            event_result["action"] = "delivery_failed"
            event_result["error"] = f"{type(exc).__name__}: {exc}"
            result["failed"] += 1
            result["pending_remaining"] += 1
        result["events"].append(event_result)

    return result


def render_text(result: dict) -> str:
    lines = [
        f"OpenLineage outbox: s3://{result['bucket']}/openlineage/outbox/",
        (
            f"Selected: {result['queued_selected']}  Already delivered: {result['already_delivered']}  "
            f"Pending found: {result['pending_found']}  Pending remaining: {result['pending_remaining']}  "
            f"Replayed: {result['replayed']}  Failed: {result['failed']}"
        ),
    ]
    for event in result["events"]:
        identity = event.get("manifest_id", event.get("outbox_key", "unknown"))
        lines.append(f"  {event['action']}: {identity}")
        if event.get("error"):
            lines.append(f"    {event['error']}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay immutable OpenLineage events without delivery receipts.")
    parser.add_argument("--object-id", help="Restrict replay to one exact media object ID")
    parser.add_argument("--manifest-id", help="Restrict replay to one exact canonical manifest UUID")
    parser.add_argument("--limit", type=int, help="Maximum number of pending events to inspect or replay")
    parser.add_argument("--dry-run", action="store_true", help="Report pending events without sending them")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-event HTTP timeout in seconds")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--bucket",
        default=os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm"),
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT"),
        help="S3-compatible endpoint",
    )
    parser.add_argument("--openlineage-url", help="Override OPENLINEAGE_URL for this replay")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = _s3_client(args.endpoint_url)
    try:
        result = replay_pending(
            client=client,
            bucket=args.bucket,
            object_id=args.object_id,
            manifest_id=args.manifest_id,
            openlineage_url=args.openlineage_url,
            timeout=args.timeout,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"OpenLineage replay failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_text(result), end="")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
