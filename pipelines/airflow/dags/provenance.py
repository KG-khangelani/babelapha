"""Canonical provenance records and OpenLineage emission for Babelapha DAGs.

This module deliberately has no Airflow or boto3 imports at module load time so
the DAG directory can still be syntax-checked in lightweight environments.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid


SCHEMA_VERSION = "1.0.0"
PRODUCER = "https://github.com/KG-khangelani/babelapha"
CONTRACTS_COMMIT = "089e23c53303b0c4b5298b12fdda11f646e3ff2b"
DELIVERY_CONTRACTS_COMMIT = "ea9f16f30ae2facc8e5215c8156e1458bc969f87"
MANIFEST_SCHEMA_URI = (
    f"{PRODUCER.replace('github.com', 'raw.githubusercontent.com')}/{CONTRACTS_COMMIT}/"
    "contracts/provenance-manifest-v1.schema.json"
)
OPENLINEAGE_FACET_SCHEMA_URI = (
    f"{PRODUCER.replace('github.com', 'raw.githubusercontent.com')}/{CONTRACTS_COMMIT}/"
    "contracts/openlineage-babelapha-execution-run-facet-v2.schema.json"
)
OPENLINEAGE_ARTIFACT_FACET_SCHEMA_URI = (
    f"{PRODUCER.replace('github.com', 'raw.githubusercontent.com')}/{CONTRACTS_COMMIT}/"
    "contracts/openlineage-babelapha-artifact-dataset-facet-v1.schema.json"
)
OPENLINEAGE_RECEIPT_SCHEMA_URI = (
    f"{PRODUCER.replace('github.com', 'raw.githubusercontent.com')}/{DELIVERY_CONTRACTS_COMMIT}/"
    "contracts/openlineage-delivery-receipt-v1.schema.json"
)
OPENLINEAGE_SCHEMA_URI = (
    "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent"
)
VALID_STATUSES = {"SUCCEEDED", "FAILED", "RETRYING", "SKIPPED"}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
GIT_SHA_RE = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
MEDIA_TYPES_BY_SUFFIX = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".mpd": "application/dash+xml",
    ".m4s": "video/iso.segment",
    ".ts": "video/mp2t",
}


class ManifestValidationError(ValueError):
    """Raised when a provenance record violates the v1 contract."""


def media_type_for_uri(uri: str, reported: str | None = None) -> str | None:
    """Resolve media pipeline formats before consulting platform MIME tables."""
    suffix = Path(urllib.parse.urlparse(uri).path).suffix.lower()
    return MEDIA_TYPES_BY_SUFFIX.get(suffix) or reported or mimetypes.guess_type(uri)[0]


def utc_iso(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(
    uri: str,
    *,
    sha256: str | None = None,
    size_bytes: int | None = None,
    media_type: str | None = None,
    kind: str = "OBJECT",
    pachyderm_commit: str | None = None,
    s3_version_id: str | None = None,
    etag: str | None = None,
) -> dict:
    """Build one artifact identity without pretending unknown hashes are exact."""
    result = {
        "uri": uri,
        "kind": kind,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "media_type": media_type_for_uri(uri, media_type),
        "integrity": "VERIFIED" if sha256 else "UNVERIFIED",
        "version": {
            "pachyderm_commit": pachyderm_commit,
            "s3_version_id": s3_version_id,
            "etag": etag.strip('"') if isinstance(etag, str) else etag,
        },
    }
    _validate_artifact(result)
    return result


def artifact_from_file(path: str | Path, *, uri: str | None = None) -> dict:
    file_path = Path(path)
    return artifact(
        uri or file_path.resolve().as_uri(),
        sha256=sha256_file(file_path),
        size_bytes=file_path.stat().st_size,
    )


def s3_artifact_from_file(
    path: str | Path,
    *,
    bucket: str,
    key: str,
    endpoint_url: str | None = None,
    pachyderm_commit: str | None = None,
) -> dict:
    """Combine exact local bytes with the corresponding S3 object identity."""
    file_path = Path(path)
    checksum = sha256_file(file_path)
    stored = _s3_client(endpoint_url or os.environ.get("MINIO_ENDPOINT")).head_object(Bucket=bucket, Key=key)
    claimed = stored.get("Metadata", {}).get("sha256")
    if claimed and claimed != checksum:
        raise ValueError(f"Stored SHA-256 metadata does not match downloaded bytes: s3://{bucket}/{key}")
    return artifact(
        f"s3://{bucket}/{key}",
        sha256=checksum,
        size_bytes=file_path.stat().st_size,
        media_type=stored.get("ContentType"),
        pachyderm_commit=pachyderm_commit,
        s3_version_id=stored.get("VersionId"),
        etag=stored.get("ETag"),
    )


def _safe_segment(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ManifestValidationError("Provenance path segments cannot be empty")
    return urllib.parse.quote(text, safe="-_.")


def manifest_key(record: dict) -> str:
    return "/".join(
        [
            "provenance",
            _safe_segment(record["object"]["id"]),
            _safe_segment(record["run"]["id"]),
            _safe_segment(record["run"]["task_id"]),
            f"{record['run']['attempt']}-{record['run']['status'].lower()}.json",
        ]
    )


def manifest_prefix(object_id: str, run_id: str) -> str:
    return f"provenance/{_safe_segment(object_id)}/{_safe_segment(run_id)}/"


def canonical_json_bytes(record: dict) -> bytes:
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _container_identity(image: str, explicit_digest: str | None = None) -> dict:
    digest = explicit_digest
    if "@sha256:" in image:
        image, digest_part = image.rsplit("@", 1)
        digest = digest or digest_part
    if digest and not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"
    verified = bool(digest and DIGEST_RE.fullmatch(digest))
    return {
        "image": image,
        "digest": digest if verified else None,
        "identity_status": "VERIFIED_DIGEST" if verified else "CONFIGURED_REF_ONLY",
    }


def build_manifest(
    *,
    object_id: str,
    filename: str,
    run_id: str,
    dag_id: str,
    task_id: str,
    stage: str,
    attempt: int,
    status: str,
    decision: dict,
    inputs: list[dict] | None = None,
    outputs: list[dict] | None = None,
    started_at: datetime | str | None = None,
    completed_at: datetime | str | None = None,
    duration_ms: int | None = None,
    git_repository: str = PRODUCER,
    git_commit: str | None = None,
    code_path: str = "unknown",
    code_sha256: str | None = None,
    container_image: str = "unknown",
    container_digest: str | None = None,
    parameters: dict | None = None,
    airflow_version: str | None = None,
    airflow_log_url: str | None = None,
    bucket: str = "pachyderm",
) -> dict:
    completed_text = completed_at if isinstance(completed_at, str) else utc_iso(completed_at)
    started_text = started_at if isinstance(started_at, str) else (utc_iso(started_at) if started_at else None)
    manifest_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"babelapha:{dag_id}:{run_id}:{task_id}:{attempt}:{status}",
        )
    )
    record = {
        "$schema": MANIFEST_SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "recorded_at": completed_text,
        "object": {"id": object_id, "filename": filename},
        "run": {
            "id": run_id,
            "dag_id": dag_id,
            "task_id": task_id,
            "stage": stage,
            "attempt": int(attempt),
            "status": status,
            "started_at": started_text,
            "completed_at": completed_text,
            "duration_ms": duration_ms,
        },
        "decision": {
            "outcome": decision.get("outcome", status.lower()),
            "reason_code": decision.get("reason_code", status),
            "message": decision.get("message", ""),
        },
        "inputs": inputs or [],
        "outputs": outputs or [],
        "execution": {
            "git": {"repository": git_repository, "commit": git_commit},
            "code": {"path": code_path, "sha256": code_sha256},
            "container": _container_identity(container_image, container_digest),
            "parameters": parameters or {},
        },
        "orchestrator": {"name": "airflow", "version": airflow_version},
        "links": {"manifest": "", "airflow_log": airflow_log_url},
    }
    key = manifest_key(record)
    record["links"]["manifest"] = f"s3://{bucket}/{key}"
    validate_manifest(record)
    return record


def _validate_artifact(item: dict) -> None:
    required = {"uri", "kind", "sha256", "size_bytes", "media_type", "integrity", "version"}
    if not isinstance(item, dict) or set(item) != required:
        raise ManifestValidationError("Artifact fields do not match the v1 contract")
    if item.get("kind") not in {"OBJECT", "PREFIX"}:
        raise ManifestValidationError("Artifact kind must be OBJECT or PREFIX")
    sha = item.get("sha256")
    if sha is not None and not SHA256_RE.fullmatch(sha):
        raise ManifestValidationError("Artifact sha256 must be 64 lowercase hex characters")
    expected_integrity = "VERIFIED" if sha else "UNVERIFIED"
    if item.get("integrity") != expected_integrity:
        raise ManifestValidationError("Artifact integrity does not match its SHA-256 evidence")
    if not isinstance(item.get("uri"), str) or not item["uri"].strip():
        raise ManifestValidationError("Artifact uri is required")
    size = item.get("size_bytes")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        raise ManifestValidationError("Artifact size_bytes must be a non-negative integer or null")
    media_type = item.get("media_type")
    if media_type is not None and not isinstance(media_type, str):
        raise ManifestValidationError("Artifact media_type must be a string or null")
    version = item.get("version")
    if not isinstance(version, dict) or set(version) != {"pachyderm_commit", "s3_version_id", "etag"}:
        raise ManifestValidationError("Artifact version fields do not match the v1 contract")
    if any(value is not None and not isinstance(value, str) for value in version.values()):
        raise ManifestValidationError("Artifact version values must be strings or null")


def _validate_timestamp(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise ManifestValidationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ManifestValidationError(f"{field} must include a timezone")


def validate_manifest(record: dict) -> None:
    required = {
        "$schema", "schema_version", "manifest_id", "recorded_at", "object",
        "run", "decision", "inputs", "outputs", "execution", "orchestrator", "links",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise ManifestValidationError("Manifest fields do not match the v1 contract")
    if record["$schema"] != MANIFEST_SCHEMA_URI:
        raise ManifestValidationError("Manifest schema URI is not the immutable v1 contract")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ManifestValidationError(f"Unsupported schema version: {record['schema_version']}")
    _validate_timestamp(record["recorded_at"], "recorded_at")
    try:
        uuid.UUID(record["manifest_id"])
    except (ValueError, TypeError) as exc:
        raise ManifestValidationError("manifest_id must be a UUID") from exc
    object_identity = record["object"]
    if not isinstance(object_identity, dict) or set(object_identity) != {"id", "filename"}:
        raise ManifestValidationError("Manifest object fields do not match the v1 contract")
    if any(not isinstance(object_identity[field], str) or not object_identity[field].strip() for field in ("id", "filename")):
        raise ManifestValidationError("Manifest object id and filename are required")
    run = record["run"]
    run_fields = {
        "id", "dag_id", "task_id", "stage", "attempt", "status",
        "started_at", "completed_at", "duration_ms",
    }
    if not isinstance(run, dict) or set(run) != run_fields:
        raise ManifestValidationError("Manifest run fields do not match the v1 contract")
    for field in ("id", "dag_id", "task_id", "stage"):
        if not isinstance(run[field], str) or not run[field].strip():
            raise ManifestValidationError(f"Manifest run {field} is required")
    if run.get("status") not in VALID_STATUSES:
        raise ManifestValidationError(f"Unsupported run status: {run.get('status')}")
    if not isinstance(run.get("attempt"), int) or isinstance(run["attempt"], bool) or run["attempt"] < 1:
        raise ManifestValidationError("Attempt must be a positive integer")
    _validate_timestamp(run["started_at"], "run.started_at", nullable=True)
    _validate_timestamp(run["completed_at"], "run.completed_at")
    duration = run["duration_ms"]
    if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration < 0):
        raise ManifestValidationError("run.duration_ms must be a non-negative integer or null")
    decision = record["decision"]
    if not isinstance(decision, dict) or set(decision) != {"outcome", "reason_code", "message"}:
        raise ManifestValidationError("Manifest decision fields do not match the v1 contract")
    if not isinstance(decision["outcome"], str) or not decision["outcome"].strip():
        raise ManifestValidationError("Decision outcome is required")
    if not isinstance(decision["message"], str):
        raise ManifestValidationError("Decision message must be a string")
    reason_code = decision.get("reason_code", "")
    if not re.fullmatch(r"[A-Z0-9_]+", reason_code):
        raise ManifestValidationError("Decision reason_code must be uppercase snake case")
    if not isinstance(record["inputs"], list) or not isinstance(record["outputs"], list):
        raise ManifestValidationError("Manifest inputs and outputs must be arrays")
    for item in [*record["inputs"], *record["outputs"]]:
        _validate_artifact(item)
    execution = record["execution"]
    if not isinstance(execution, dict) or set(execution) != {"git", "code", "container", "parameters"}:
        raise ManifestValidationError("Manifest execution fields do not match the v1 contract")
    git = execution["git"]
    if not isinstance(git, dict) or set(git) != {"repository", "commit"}:
        raise ManifestValidationError("Manifest Git fields do not match the v1 contract")
    if not isinstance(git["repository"], str):
        raise ManifestValidationError("Git repository must be a string")
    code = execution["code"]
    if not isinstance(code, dict) or set(code) != {"path", "sha256"}:
        raise ManifestValidationError("Manifest code fields do not match the v1 contract")
    if not isinstance(code["path"], str) or not code["path"].strip():
        raise ManifestValidationError("Code path is required")
    code_sha = code["sha256"]
    if code_sha is not None and not SHA256_RE.fullmatch(code_sha):
        raise ManifestValidationError("Code sha256 must be 64 lowercase hex characters or null")
    container = execution["container"]
    if not isinstance(container, dict) or set(container) != {"image", "digest", "identity_status"}:
        raise ManifestValidationError("Manifest container fields do not match the v1 contract")
    if not isinstance(container["image"], str) or not container["image"].strip():
        raise ManifestValidationError("Container image is required")
    digest = container.get("digest")
    if digest is not None and not DIGEST_RE.fullmatch(digest):
        raise ManifestValidationError("Container digest must be sha256:<64 lowercase hex>")
    expected_identity = "VERIFIED_DIGEST" if digest else "CONFIGURED_REF_ONLY"
    if container["identity_status"] != expected_identity:
        raise ManifestValidationError("Container identity status does not match its digest evidence")
    if not isinstance(execution["parameters"], dict):
        raise ManifestValidationError("Execution parameters must be an object")
    git_commit = git.get("commit")
    if git_commit is not None and not GIT_SHA_RE.fullmatch(git_commit):
        raise ManifestValidationError("Git commit must be a full 40- or 64-character lowercase SHA")
    orchestrator = record["orchestrator"]
    if not isinstance(orchestrator, dict) or set(orchestrator) != {"name", "version"}:
        raise ManifestValidationError("Manifest orchestrator fields do not match the v1 contract")
    if orchestrator["name"] != "airflow":
        raise ManifestValidationError("Manifest orchestrator must be airflow")
    if orchestrator["version"] is not None and not isinstance(orchestrator["version"], str):
        raise ManifestValidationError("Orchestrator version must be a string or null")
    links = record["links"]
    if not isinstance(links, dict) or set(links) != {"manifest", "airflow_log"}:
        raise ManifestValidationError("Manifest link fields do not match the v1 contract")
    if not isinstance(links["manifest"], str) or not links["manifest"].startswith("s3://"):
        raise ManifestValidationError("Manifest link must be an S3 URI")
    if links["airflow_log"] is not None and not isinstance(links["airflow_log"], str):
        raise ManifestValidationError("Airflow log link must be a string or null")


def _s3_client(endpoint_url: str | None = None):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def _is_precondition_conflict(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"PreconditionFailed", "ConditionalRequestConflict", "409", "412"} or status in {
        409,
        412,
    }


def _put_immutable_bytes(
    *,
    client,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    metadata: dict[str, str],
    equivalent=None,
) -> str:
    """Atomically create one object and accept only an equivalent duplicate."""
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata=metadata,
            IfNoneMatch="*",
        )
    except Exception as exc:
        if not _is_precondition_conflict(exc):
            raise
        current = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        matches = equivalent(current, body) if equivalent else current == body
        if matches:
            return f"s3://{bucket}/{key}"
        raise FileExistsError(f"Refusing to overwrite immutable object s3://{bucket}/{key}") from exc
    return f"s3://{bucket}/{key}"


def persist_manifest(record: dict, *, endpoint_url: str | None = None, bucket: str | None = None) -> str:
    """Persist an immutable manifest; an identical retry is idempotent."""
    validate_manifest(record)
    target_bucket = bucket or os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm")
    key = manifest_key(record)
    body = canonical_json_bytes(record)
    client = _s3_client(endpoint_url or os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT"))
    return _put_immutable_bytes(
        client=client,
        bucket=target_bucket,
        key=key,
        body=body,
        content_type="application/schema+json",
        metadata={"schema-version": SCHEMA_VERSION, "manifest-id": record["manifest_id"]},
    )


def upload_file_artifact(
    path: str | Path,
    *,
    bucket: str,
    key: str,
    endpoint_url: str | None = None,
    pachyderm_commit: str | None = None,
) -> dict:
    """Upload a file with its SHA-256 metadata and return its stored identity."""
    file_path = Path(path)
    checksum = sha256_file(file_path)
    client = _s3_client(endpoint_url or os.environ.get("MINIO_ENDPOINT"))
    client.upload_file(
        str(file_path),
        bucket,
        key,
        ExtraArgs={
            "ContentType": media_type_for_uri(file_path.name) or "application/octet-stream",
            "Metadata": {"sha256": checksum},
        },
    )
    stored = client.head_object(Bucket=bucket, Key=key)
    return artifact(
        f"s3://{bucket}/{key}",
        sha256=checksum,
        size_bytes=file_path.stat().st_size,
        media_type=stored.get("ContentType"),
        pachyderm_commit=pachyderm_commit,
        s3_version_id=stored.get("VersionId"),
        etag=stored.get("ETag"),
    )


def assert_success_manifests(
    *,
    object_id: str,
    run_id: str,
    task_ids: list[str],
    endpoint_url: str | None = None,
    bucket: str | None = None,
) -> list[str]:
    """Require schema-valid success manifests and their exact queued lineage events."""
    target_bucket = bucket or os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm")
    prefix = manifest_prefix(object_id, run_id)
    client = _s3_client(endpoint_url or os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT"))
    paginator = client.get_paginator("list_objects_v2")
    keys = {
        item["Key"]
        for page in paginator.paginate(Bucket=target_bucket, Prefix=prefix)
        for item in page.get("Contents", [])
    }
    required_keys: list[str] = []
    missing = []
    for task_id in dict.fromkeys(task_ids):
        task_prefix = f"{prefix}{_safe_segment(task_id)}/"
        task_keys = sorted(
            key for key in keys if key.startswith(task_prefix) and key.endswith("-succeeded.json")
        )
        if not task_keys:
            missing.append(task_id)
        required_keys.extend(task_keys)
    if missing:
        raise RuntimeError(f"Missing immutable success manifests for: {', '.join(missing)}")

    problems = []
    locations = []
    for key in required_keys:
        try:
            manifest_body = client.get_object(Bucket=target_bucket, Key=key)["Body"].read()
            record = json.loads(manifest_body)
            validate_manifest(record)
            if record["object"]["id"] != object_id:
                raise ManifestValidationError("manifest object ID does not match the requested object")
            if record["run"]["id"] != run_id:
                raise ManifestValidationError("manifest run ID does not match the requested run")
            if record["run"]["task_id"] not in task_ids or record["run"]["status"] != "SUCCEEDED":
                raise ManifestValidationError("manifest task or status does not match the required success record")
            if manifest_key(record) != key:
                raise ManifestValidationError("manifest identity does not match its immutable object key")
            manifest_uri = f"s3://{target_bucket}/{key}"
            if record["links"]["manifest"] != manifest_uri:
                raise ManifestValidationError("manifest link does not match its immutable object key")

            expected_event = build_openlineage_event(record)
            outbox_key = openlineage_event_key(expected_event, "outbox")
            event_body = client.get_object(Bucket=target_bucket, Key=outbox_key)["Body"].read()
            event = json.loads(event_body)
            if canonical_json_bytes(event) != event_body:
                raise ManifestValidationError("queued OpenLineage event bytes are not canonical")
            if openlineage_event_key(event, "outbox") != outbox_key:
                raise ManifestValidationError("queued OpenLineage event identity does not match its object key")
            validate_openlineage_event_for_manifest(event, record)
            locations.append(manifest_uri)
        except Exception as exc:
            problems.append(f"{key}: {type(exc).__name__}: {exc}")
    if problems:
        raise RuntimeError("Invalid manifest/OpenLineage evidence:\n- " + "\n- ".join(problems))
    return locations


def _artifact_facet(item: dict) -> dict:
    version = item["version"]
    return {
        "_producer": PRODUCER,
        "_schemaURL": OPENLINEAGE_ARTIFACT_FACET_SCHEMA_URI,
        "uri": item["uri"],
        "kind": item["kind"],
        "sha256": item["sha256"],
        "sizeBytes": item["size_bytes"],
        "mediaType": item["media_type"],
        "integrity": item["integrity"],
        "pachydermCommit": version["pachyderm_commit"],
        "s3VersionId": version["s3_version_id"],
        "etag": version["etag"],
    }


def _dataset(item: dict, *, role: str) -> dict:
    if role not in {"input", "output"}:
        raise ValueError(f"Unsupported OpenLineage dataset role: {role}")
    parsed = urllib.parse.urlparse(item["uri"])
    namespace = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else "babelapha"
    name = parsed.path.lstrip("/") or item["uri"]
    return {
        "namespace": namespace,
        "name": name,
        "facets": {},
        f"{role}Facets": {"babelapha_artifact": _artifact_facet(item)},
    }


def build_openlineage_event(record: dict) -> dict:
    validate_manifest(record)
    event_type = {
        "SUCCEEDED": "COMPLETE",
        "FAILED": "FAIL",
        "RETRYING": "FAIL",
        "SKIPPED": "ABORT",
    }[record["run"]["status"]]
    execution = record["execution"]
    run = record["run"]
    decision = record["decision"]
    code = execution["code"]
    container = execution["container"]
    orchestrator = record["orchestrator"]
    facet = {
        "_producer": PRODUCER,
        "_schemaURL": OPENLINEAGE_FACET_SCHEMA_URI,
        "schemaVersion": record["schema_version"],
        "manifestId": record["manifest_id"],
        "manifestUri": record["links"]["manifest"],
        "recordedAt": record["recorded_at"],
        "objectId": record["object"]["id"],
        "objectFilename": record["object"]["filename"],
        "airflowRunId": run["id"],
        "dagId": run["dag_id"],
        "taskId": run["task_id"],
        "stage": run["stage"],
        "attempt": run["attempt"],
        "status": run["status"],
        "startedAt": run["started_at"],
        "completedAt": run["completed_at"],
        "durationMs": run["duration_ms"],
        "decisionOutcome": decision["outcome"],
        "decisionReasonCode": decision["reason_code"],
        "decisionMessage": decision["message"],
        "gitRepository": execution["git"]["repository"],
        "gitCommit": execution["git"]["commit"],
        "codePath": code["path"],
        "codeSha256": code["sha256"],
        "containerImage": container["image"],
        "containerDigest": container["digest"],
        "containerIdentityStatus": container["identity_status"],
        "parameters": execution["parameters"],
        "orchestratorName": orchestrator["name"],
        "orchestratorVersion": orchestrator["version"],
        "airflowLogUrl": record["links"]["airflow_log"],
    }
    return {
        "eventType": event_type,
        "eventTime": record["run"]["completed_at"],
        "run": {"runId": record["manifest_id"], "facets": {"babelapha_execution": facet}},
        "job": {
            "namespace": os.environ.get("OPENLINEAGE_NAMESPACE", "babelapha"),
            "name": f"{record['run']['dag_id']}.{record['run']['task_id']}",
            "facets": {},
        },
        "inputs": [_dataset(item, role="input") for item in record["inputs"]],
        "outputs": [_dataset(item, role="output") for item in record["outputs"]],
        "producer": PRODUCER,
        "schemaURL": OPENLINEAGE_SCHEMA_URI,
    }


def _openlineage_execution_facet(event: dict) -> dict:
    try:
        facet = event["run"]["facets"]["babelapha_execution"]
    except (KeyError, TypeError) as exc:
        raise ManifestValidationError("OpenLineage event is missing the Babelapha execution facet") from exc
    if event["run"].get("runId") != facet.get("manifestId"):
        raise ManifestValidationError("OpenLineage runId must equal the canonical manifest ID")
    expected_event_type = {
        "SUCCEEDED": "COMPLETE",
        "FAILED": "FAIL",
        "RETRYING": "FAIL",
        "SKIPPED": "ABORT",
    }.get(facet.get("status"))
    if expected_event_type is None or event.get("eventType") != expected_event_type:
        raise ManifestValidationError("OpenLineage event type does not match the manifest attempt status")
    for role, items in (("input", event.get("inputs", [])), ("output", event.get("outputs", []))):
        for item in items:
            try:
                item[f"{role}Facets"]["babelapha_artifact"]
            except (KeyError, TypeError) as exc:
                raise ManifestValidationError(
                    f"OpenLineage {role} dataset is missing its Babelapha artifact facet"
                ) from exc
    return facet


def validate_openlineage_event_for_manifest(event: dict, record: dict) -> None:
    """Prove that one queued event carries every fact from its canonical manifest."""
    validate_manifest(record)
    _openlineage_execution_facet(event)
    try:
        namespace = event["job"]["namespace"]
    except (KeyError, TypeError) as exc:
        raise ManifestValidationError("OpenLineage job namespace is missing") from exc
    if not isinstance(namespace, str) or not namespace.strip():
        raise ManifestValidationError("OpenLineage job namespace is required")
    expected = build_openlineage_event(record)
    expected["job"]["namespace"] = namespace
    if event != expected:
        raise ManifestValidationError("OpenLineage event facts differ from the canonical manifest")


def openlineage_event_key(event: dict, state: str) -> str:
    """Return the paired immutable outbox or delivery-receipt key."""
    if state not in {"outbox", "delivered"}:
        raise ValueError(f"Unsupported OpenLineage delivery state: {state}")
    facet = _openlineage_execution_facet(event)
    return "/".join(
        [
            "openlineage",
            state,
            _safe_segment(facet["objectId"]),
            _safe_segment(facet["airflowRunId"]),
            _safe_segment(facet["taskId"]),
            f"{int(facet['attempt'])}-{str(facet['status']).lower()}.json",
        ]
    )


def persist_openlineage_event(
    event: dict,
    *,
    endpoint_url: str | None = None,
    bucket: str | None = None,
    client=None,
) -> str:
    """Store the exact OpenLineage event before any network delivery attempt."""
    facet = _openlineage_execution_facet(event)
    body = canonical_json_bytes(event)
    target_bucket = bucket or os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm")
    storage = client or _s3_client(
        endpoint_url or os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT")
    )
    return _put_immutable_bytes(
        client=storage,
        bucket=target_bucket,
        key=openlineage_event_key(event, "outbox"),
        body=body,
        content_type="application/json",
        metadata={
            "manifest-id": facet["manifestId"],
            "event-sha256": hashlib.sha256(body).hexdigest(),
        },
    )


def persist_openlineage_outbox(
    record: dict,
    *,
    endpoint_url: str | None = None,
    bucket: str | None = None,
    client=None,
) -> str:
    """Build and store the OpenLineage event for a canonical manifest."""
    return persist_openlineage_event(
        build_openlineage_event(record),
        endpoint_url=endpoint_url,
        bucket=bucket,
        client=client,
    )


def _openlineage_target(url: str | None = None) -> str | None:
    endpoint = (url or os.environ.get("OPENLINEAGE_URL", "")).rstrip("/")
    if not endpoint or os.environ.get("OPENLINEAGE_DISABLED", "").lower() in {"1", "true", "yes"}:
        return None
    path = os.environ.get("OPENLINEAGE_ENDPOINT", "/api/v1/lineage")
    return endpoint + "/" + path.lstrip("/")


def emit_openlineage_event(
    event: dict,
    *,
    url: str | None = None,
    target: str | None = None,
    timeout: float = 5.0,
) -> int | None:
    """Send one already-materialized event and return the accepting HTTP status."""
    _openlineage_execution_facet(event)
    resolved_target = target or _openlineage_target(url)
    if not resolved_target:
        return None
    request = urllib.request.Request(
        resolved_target,
        data=canonical_json_bytes(event),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"OpenLineage endpoint returned HTTP {response.status}")
        return response.status


def emit_openlineage(record: dict, *, url: str | None = None, timeout: float = 5.0) -> bool:
    """Compatibility wrapper that builds and sends an event from a manifest."""
    return emit_openlineage_event(build_openlineage_event(record), url=url, timeout=timeout) is not None


def _equivalent_delivery_receipts(current: bytes, desired: bytes) -> bool:
    try:
        current_record = json.loads(current)
        desired_record = json.loads(desired)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not current_record.get("delivered_at") or not desired_record.get("delivered_at"):
        return False
    current_record.pop("delivered_at", None)
    desired_record.pop("delivered_at", None)
    return current_record == desired_record


def validate_openlineage_receipt(receipt: dict, event: dict, *, outbox_uri: str) -> None:
    """Validate the receipt identity against the exact queued event."""
    facet = _openlineage_execution_facet(event)
    required = {
        "$schema",
        "schema_version",
        "manifest_id",
        "object_id",
        "airflow_run_id",
        "task_id",
        "attempt",
        "status",
        "event_type",
        "outbox_uri",
        "event_sha256",
        "endpoint",
        "http_status",
        "delivered_at",
    }
    if set(receipt) != required:
        raise ManifestValidationError("OpenLineage delivery receipt fields do not match the v1 contract")
    expected = {
        "$schema": OPENLINEAGE_RECEIPT_SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "manifest_id": facet["manifestId"],
        "object_id": facet["objectId"],
        "airflow_run_id": facet["airflowRunId"],
        "task_id": facet["taskId"],
        "attempt": facet["attempt"],
        "status": facet["status"],
        "event_type": event["eventType"],
        "outbox_uri": outbox_uri,
        "event_sha256": hashlib.sha256(canonical_json_bytes(event)).hexdigest(),
    }
    for field, expected_value in expected.items():
        if receipt.get(field) != expected_value:
            raise ManifestValidationError(f"OpenLineage delivery receipt has the wrong {field}")
    if not isinstance(receipt["endpoint"], str) or not urllib.parse.urlparse(receipt["endpoint"]).scheme:
        raise ManifestValidationError("OpenLineage delivery receipt endpoint must be an absolute URI")
    if not isinstance(receipt["http_status"], int) or not 200 <= receipt["http_status"] <= 299:
        raise ManifestValidationError("OpenLineage delivery receipt HTTP status must be 2xx")
    try:
        delivered_at = datetime.fromisoformat(receipt["delivered_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ManifestValidationError("OpenLineage delivery receipt timestamp is invalid") from exc
    if delivered_at.tzinfo is None:
        raise ManifestValidationError("OpenLineage delivery receipt timestamp must include a timezone")


def persist_openlineage_receipt(
    event: dict,
    *,
    outbox_uri: str,
    openlineage_target: str,
    http_status: int,
    endpoint_url: str | None = None,
    bucket: str | None = None,
    client=None,
) -> str:
    """Acknowledge delivery of the exact queued bytes without mutating the outbox."""
    facet = _openlineage_execution_facet(event)
    if not 200 <= int(http_status) <= 299:
        raise ValueError("A delivery receipt requires an accepting 2xx HTTP status")
    event_body = canonical_json_bytes(event)
    receipt = {
        "$schema": OPENLINEAGE_RECEIPT_SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "manifest_id": facet["manifestId"],
        "object_id": facet["objectId"],
        "airflow_run_id": facet["airflowRunId"],
        "task_id": facet["taskId"],
        "attempt": facet["attempt"],
        "status": facet["status"],
        "event_type": event["eventType"],
        "outbox_uri": outbox_uri,
        "event_sha256": hashlib.sha256(event_body).hexdigest(),
        "endpoint": openlineage_target,
        "http_status": int(http_status),
        "delivered_at": utc_iso(),
    }
    validate_openlineage_receipt(receipt, event, outbox_uri=outbox_uri)
    body = canonical_json_bytes(receipt)
    target_bucket = bucket or os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm")
    storage = client or _s3_client(
        endpoint_url or os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get("MINIO_ENDPOINT")
    )
    return _put_immutable_bytes(
        client=storage,
        bucket=target_bucket,
        key=openlineage_event_key(event, "delivered"),
        body=body,
        content_type="application/schema+json",
        metadata={
            "schema-version": SCHEMA_VERSION,
            "manifest-id": facet["manifestId"],
            "event-sha256": receipt["event_sha256"],
        },
        equivalent=_equivalent_delivery_receipts,
    )


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _dag_code_identity(context: dict) -> tuple[str, str | None]:
    task = context.get("task")
    dag = getattr(task, "dag", None)
    path = getattr(dag, "fileloc", None) or getattr(task, "dag_id", "unknown")
    try:
        return str(path), sha256_file(path)
    except (OSError, TypeError):
        return str(path), None


def _git_commit(identity_file: str | Path | None = None) -> str | None:
    configured = os.environ.get("BABELAPHA_GIT_SHA")
    if configured and GIT_SHA_RE.fullmatch(configured.strip().lower()):
        return configured.strip().lower()
    deployed_identity = Path(identity_file) if identity_file else Path(__file__).with_name(".babelapha-git-sha")
    try:
        deployed_commit = deployed_identity.read_text(encoding="utf-8").strip().lower()
        if GIT_SHA_RE.fullmatch(deployed_commit):
            return deployed_commit
    except OSError:
        pass
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return None


def _duration_ms(started: datetime | None, completed: datetime) -> int | None:
    if not started:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    return max(0, int((completed - started).total_seconds() * 1000))


def _task_payload(context: dict) -> dict:
    ti = context.get("task_instance") or context.get("ti")
    if ti is None:
        return {}
    candidates = [
        ti.task_id,
        "upload_results",
        "transcode",
        "validate_media",
        "virus_scan",
        "download_from_minio",
        "download_from_pachyderm",
        "inspect_source",
        "validate_inputs",
    ]
    for task_id in dict.fromkeys(candidates):
        try:
            value = ti.xcom_pull(task_ids=task_id)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return {}


def build_airflow_manifest(context: dict, status: str) -> dict:
    """Translate an Airflow callback context into the canonical manifest."""
    ti = context.get("task_instance") or context.get("ti")
    dag_run = context.get("dag_run")
    task = context.get("task") or getattr(ti, "task", None)
    conf = getattr(dag_run, "conf", None) or {}
    payload = _task_payload(context)
    object_id = str(payload.get("object_id") or conf.get("id") or "unknown")
    filename = str(payload.get("filename") or conf.get("filename") or "unknown")
    task_id = str(getattr(ti, "task_id", getattr(task, "task_id", "unknown")))
    dag_id = str(getattr(ti, "dag_id", getattr(task, "dag_id", "unknown")))
    run_id = str(getattr(dag_run, "run_id", context.get("run_id", "unknown")))
    attempt = max(1, int(getattr(ti, "try_number", 1) or 1))
    completed = getattr(ti, "end_date", None) or datetime.now(timezone.utc)
    started = getattr(ti, "start_date", None)
    error = context.get("exception")
    decision = payload.get("provenance_decision") or {}
    if status != "SUCCEEDED":
        decision = {
            "outcome": status.lower(),
            "reason_code": f"TASK_{status}",
            "message": str(error or decision.get("message") or "Task did not complete successfully")[:1000],
        }
    else:
        decision = {
            "outcome": decision.get("outcome", "completed"),
            "reason_code": decision.get("reason_code", "TASK_COMPLETED"),
            "message": decision.get("message", "Task completed successfully"),
        }
    code_path, code_sha = _dag_code_identity(context)
    task_env_key = re.sub(r"[^A-Z0-9]", "_", task_id.upper())
    task_image = getattr(task, "image", None)
    if task_image:
        image = str(task_image)
        digest = os.environ.get(f"BABELAPHA_{task_env_key}_IMAGE_DIGEST")
    else:
        image = os.environ.get("BABELAPHA_RUNTIME_IMAGE", "apache-airflow")
        digest = os.environ.get("BABELAPHA_RUNTIME_IMAGE_DIGEST")
    bucket = os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get("S3_BUCKET", "pachyderm")
    manifest_inputs = payload.get("provenance_inputs") or []
    if not manifest_inputs and payload.get("s3_input_key"):
        manifest_inputs = [artifact(f"s3://{payload.get('s3_bucket', bucket)}/{payload['s3_input_key']}")]
    manifest_outputs = payload.get("provenance_outputs") or [] if status == "SUCCEEDED" else []
    return build_manifest(
        object_id=object_id,
        filename=filename,
        run_id=run_id,
        dag_id=dag_id,
        task_id=task_id,
        stage=str(payload.get("provenance_stage") or task_id) if status == "SUCCEEDED" else task_id,
        attempt=attempt,
        status=status,
        decision=decision,
        inputs=manifest_inputs,
        outputs=manifest_outputs,
        started_at=started,
        completed_at=completed,
        duration_ms=_duration_ms(started, completed),
        git_commit=_git_commit(),
        code_path=code_path,
        code_sha256=code_sha,
        container_image=image,
        container_digest=digest,
        parameters={"object_id": object_id, "filename": filename},
        airflow_version=_package_version("apache-airflow"),
        airflow_log_url=getattr(ti, "log_url", None),
        bucket=bucket,
    )


def emit_airflow_manifest(context: dict, status: str) -> None:
    """Persist canonical evidence and a replayable OpenLineage delivery pair."""
    try:
        record = build_airflow_manifest(context, status)
        location = persist_manifest(record)
        print(f"[provenance] Stored immutable record: {location}")
    except Exception as exc:
        # Callback failures must be loud without masking the task's original state.
        print(f"[provenance] ERROR: {type(exc).__name__}: {exc}")
        return

    try:
        event = build_openlineage_event(record)
        outbox_uri = persist_openlineage_event(event)
        print(f"[provenance] Queued immutable OpenLineage event: {outbox_uri}")
    except Exception as exc:
        print(f"[provenance] ERROR queuing OpenLineage event: {type(exc).__name__}: {exc}")
        return

    target = _openlineage_target()
    if not target:
        print(f"[provenance] OpenLineage event pending: endpoint disabled or not configured ({outbox_uri})")
        return

    try:
        http_status = emit_openlineage_event(event, target=target)
        if http_status is None:  # Defensive: target was resolved immediately above.
            print(f"[provenance] OpenLineage event pending: endpoint unavailable ({outbox_uri})")
            return
        receipt_uri = persist_openlineage_receipt(
            event,
            outbox_uri=outbox_uri,
            openlineage_target=target,
            http_status=http_status,
        )
        print(f"[provenance] Emitted OpenLineage event: {record['manifest_id']}")
        print(f"[provenance] Stored immutable delivery receipt: {receipt_uri}")
    except Exception as exc:
        print(f"[provenance] OpenLineage event pending after delivery error: {type(exc).__name__}: {exc}")


def provenance_success_callback(context: dict) -> None:
    emit_airflow_manifest(context, "SUCCEEDED")


def provenance_failure_callback(context: dict) -> None:
    emit_airflow_manifest(context, "FAILED")


def provenance_retry_callback(context: dict) -> None:
    emit_airflow_manifest(context, "RETRYING")
