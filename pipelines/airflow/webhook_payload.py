"""Validated contract between Pachyderm-style events and Airflow DAG runs."""

from __future__ import annotations

import hashlib
import re
from typing import Any


COMMIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _commit_candidates(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, dict):
        return []
    candidates = []
    for key in ("id", "commit_id", "commitId"):
        candidate = _text(value.get(key))
        if candidate:
            candidates.append(candidate)
    nested = value.get("commit")
    if nested is not value:
        candidates.extend(_commit_candidates(nested))
    return candidates


def extract_pachyderm_commit(payload: dict) -> str:
    """Read the exact commit from supported flat and protobuf-JSON shapes."""
    candidates = []
    for key in ("pachyderm_commit", "commit_id", "commitId"):
        candidate = _text(payload.get(key))
        if candidate:
            candidates.append(candidate)
    for key in ("commit", "commit_info", "commitInfo"):
        candidates.extend(_commit_candidates(payload.get(key)))

    unique_candidates = set(candidates)
    if not unique_candidates:
        raise ValueError("Webhook payload must include an exact Pachyderm commit ID")
    if len(unique_candidates) != 1:
        raise ValueError("Webhook payload contains conflicting Pachyderm commit IDs")
    candidate = unique_candidates.pop()
    if not COMMIT_RE.fullmatch(candidate):
        raise ValueError("Pachyderm commit ID contains unsupported characters or exceeds 256 characters")
    return candidate


def _file_identity(payload: dict) -> tuple[str, str]:
    direct_object_id = _text(payload.get("id"))
    direct_filename = _text(payload.get("filename"))
    path = _text(payload.get("path")).strip("/")
    path_object_id = ""
    path_filename = ""
    if path:
        parts = path.split("/") if path else []
        if len(parts) < 3 or parts[0] != "incoming":
            raise ValueError("Webhook payload needs id and filename, or an incoming/<id>/<filename> path")
        path_object_id = parts[1]
        path_filename = "/".join(parts[2:])
    if direct_object_id and path_object_id and direct_object_id != path_object_id:
        raise ValueError("Webhook payload contains conflicting object IDs")
    if direct_filename and path_filename and direct_filename.replace("\\", "/") != path_filename:
        raise ValueError("Webhook payload contains conflicting filenames")

    object_id = direct_object_id or path_object_id
    filename = direct_filename or path_filename
    if not object_id or not filename:
        raise ValueError("Webhook payload needs id and filename, or an incoming/<id>/<filename> path")

    filename_parts = filename.replace("\\", "/").split("/")
    if (
        not object_id
        or object_id in {".", ".."}
        or "/" in object_id
        or "\\" in object_id
        or not filename
        or any(part in {"", ".", ".."} for part in filename_parts)
        or any(ord(character) < 32 for character in object_id + filename)
    ):
        raise ValueError("Webhook object ID or filename is unsafe")
    return object_id, "/".join(filename_parts)


def build_dag_conf(payload: dict) -> dict[str, str]:
    """Return the complete, lossless lineage identity required by the DAG."""
    if not isinstance(payload, dict):
        raise ValueError("Webhook payload must be a JSON object")
    action = _text(payload.get("action")).lower()
    if action and action not in {"put_file", "putfile"}:
        raise ValueError(f"Unsupported Pachyderm action: {action}")
    object_id, filename = _file_identity(payload)
    return {
        "id": object_id,
        "filename": filename,
        "pachyderm_commit": extract_pachyderm_commit(payload),
    }


def dag_run_id(conf: dict[str, str]) -> str:
    """Derive an idempotent run ID without weakening the full conf identity."""
    commit = re.sub(r"[^A-Za-z0-9_.-]", "_", conf["pachyderm_commit"])[:80]
    object_fingerprint = hashlib.sha256(
        f"{conf['id']}\0{conf['filename']}".encode("utf-8")
    ).hexdigest()[:16]
    return f"pachyderm__{commit}__{object_fingerprint}"
