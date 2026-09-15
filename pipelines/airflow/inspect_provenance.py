#!/usr/bin/env python3
"""Inspect all immutable provenance records for one media object."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Iterable


DAGS_DIR = Path(__file__).resolve().parent / "dags"
sys.path.insert(0, str(DAGS_DIR))

from provenance import _s3_client, _safe_segment, manifest_prefix, validate_manifest  # noqa: E402


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


def build_view(object_id: str, records: Iterable[dict]) -> dict:
    """Group validated records by Airflow run without inventing run state."""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        validate_manifest(record)
        if record["object"]["id"] != object_id:
            raise ValueError(f"Expected object {object_id!r}, got {record['object']['id']!r}")
        grouped.setdefault(record["run"]["id"], []).append(record)

    runs = []
    for run_id, run_records in sorted(grouped.items()):
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
                "statuses_observed": sorted({record["run"]["status"] for record in ordered}),
                "first_recorded_at": ordered[0]["recorded_at"],
                "last_recorded_at": ordered[-1]["recorded_at"],
                "records": ordered,
            }
        )
    return {"object_id": object_id, "run_count": len(runs), "record_count": sum(map(len, grouped.values())), "runs": runs}


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
    ]
    for run in view["runs"]:
        lines.extend(
            [
                "",
                f"Run: {run['run_id']}",
                f"Observed statuses: {', '.join(run['statuses_observed'])}",
                f"Evidence window: {run['first_recorded_at']} -> {run['last_recorded_at']}",
            ]
        )
        for record in run["records"]:
            task = record["run"]
            decision = record["decision"]
            execution = record["execution"]
            container = execution["container"]
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
                ]
            )
    return "\n".join(lines) + "\n"


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
    view = build_view(args.object_id, records)
    if args.format == "json":
        print(json.dumps(view, indent=2, sort_keys=True))
    else:
        print(render_text(view), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
