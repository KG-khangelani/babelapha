#!/usr/bin/env python3
"""Dependency-free trust boundary for the local Mathematica media prototype.

Python owns byte identity, strict JSON validation, safe relative paths, and
canonical serialization.  Mathematica owns every media measurement and every
human-facing analytical artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tempfile
import wave


SCHEMA_VERSION = "1.0.0"
ANALYSIS_ID = "mathematica-local-media-lab-v1"
CANONICALIZATION = "SORTED_INDENTED_JSON_V1"
PACKAGE_KERNEL_DIRECTORY = (
    Path(__file__).resolve().parent / "BabelaphaAnalysis" / "Kernel"
)

DEFAULT_PARAMETERS = {
    "silence_threshold_db": -40.0,
    "frame_seconds": 0.04,
    "hop_seconds": 0.02,
    "random_seed": 20260916,
}

VIDEO_MEDIA_TYPES = {
    ".avi": "video/x-msvideo",
    ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".ts": "video/mp2t",
    ".webm": "video/webm",
}

CAPABILITY_KEYS = {
    "video_import",
    "audio_track",
    "video_summary_plot",
    "frame_analysis",
    "time_series",
    "event_series",
    "tabular",
    "notebook_export",
}
CAPABILITY_STATUSES = {"USED", "UNAVAILABLE", "NOT_APPLICABLE"}

EXPECTED_OUTPUT_MEDIA_TYPES = {
    "analysis-notebook.nb": "application/vnd.wolfram.mathematica",
    "audio-overview.png": "image/png",
    "audio-overview.svg": "image/svg+xml",
    "report.html": "text/html",
    "report.md": "text/markdown",
    "video-contact-sheet.png": "image/png",
    "video-summary.png": "image/png",
}

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class BoundaryError(ValueError):
    """A stable, user-safe local boundary failure."""

    reason_code = "BOUNDARY_ERROR"
    exit_code = 2


class InputContractError(BoundaryError):
    reason_code = "INVALID_ANALYSIS_INPUT"
    exit_code = 2


class IntegrityError(BoundaryError):
    reason_code = "INTEGRITY_CHECK_FAILED"
    exit_code = 3


class ResultContractError(BoundaryError):
    reason_code = "INVALID_ANALYSIS_RESULT"
    exit_code = 4


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r} is forbidden")
        result[key] = value
    return result


def load_json(path: Path, error_type: type[BoundaryError] = InputContractError) -> dict:
    """Load strict UTF-8 JSON, rejecting duplicate keys and non-finite values."""
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError("UTF-8 BOM is forbidden")
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_object_without_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise error_type(f"Cannot read strict JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise error_type(f"{path} must contain one JSON object")
    return value


def _validate_json_value(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BoundaryError(f"{path} must be finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise BoundaryError(f"{path} has an empty or non-string object key")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise BoundaryError(f"{path} contains unsupported value type {type(value).__name__}")


def canonical_json_bytes(value: dict) -> bytes:
    """Return Babelapha's sorted, indented, newline-terminated JSON bytes."""
    _validate_json_value(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_source_hash(directory: Path = PACKAGE_KERNEL_DIRECTORY) -> str:
    """Match BabelaphaAnalysis`PackageSourceHash using portable file digests."""
    files = sorted(directory.glob("*.wl"), key=lambda path: path.name.casefold())
    if not files:
        raise InputContractError(f"No Wolfram package sources found in {directory}")
    components = [f"{path.name}:{sha256_file(path)}" for path in files]
    return hashlib.sha256("\n".join(components).encode("utf-8")).hexdigest()


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: dict) -> None:
    _atomic_write(path, canonical_json_bytes(value))


def _workspace_path(workspace: str | Path) -> Path:
    path = Path(workspace).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise InputContractError(f"Workspace is not a directory: {path}")
    return path


def initialize_workspace(workspace: str | Path) -> dict:
    """Create the local workflow directories without deleting content."""
    root = _workspace_path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    directories = {}
    for name in ("ingest", "artefacts", "output", "logs", "work"):
        path = root / name
        if path.exists() and (not path.is_dir() or path.is_symlink()):
            raise InputContractError(
                f"Workspace entry {name!r} must be a real directory, not a link"
            )
        path.mkdir(exist_ok=True)
        directories[name] = str(path)
    return {"workspace": str(root), "directories": directories}


def _strict_fields(value: object, expected: set[str], path: str, error_type) -> dict:
    if not isinstance(value, dict):
        raise error_type(f"{path} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise error_type(f"{path} fields differ; missing={missing}, unknown={unknown}")
    return value


def _string(value: object, path: str, error_type, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise error_type(f"{path} must be {'a non-empty' if nonempty else 'a'} string")
    return value


def _integer(value: object, path: str, error_type, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise error_type(f"{path} must be at least {minimum}")
    return value


def _number(
    value: object,
    path: str,
    error_type,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    nullable: bool = False,
) -> float | int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"{path} must be a finite number" + (" or null" if nullable else ""))
    if not math.isfinite(value):
        raise error_type(f"{path} must be finite")
    if minimum is not None and value < minimum:
        raise error_type(f"{path} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise error_type(f"{path} must be at most {maximum}")
    return value


def _sha256(value: object, path: str, error_type) -> str:
    value = _string(value, path, error_type)
    if not _SHA256_RE.fullmatch(value):
        raise error_type(f"{path} must be 64 lowercase hexadecimal characters")
    return value


def _safe_relative_path(value: object, root_name: str, path: str, error_type) -> str:
    value = _string(value, path, error_type)
    if "\\" in value:
        raise error_type(f"{path} must use portable forward slashes")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or candidate.parts[0] != root_name:
        raise error_type(f"{path} must be relative to {root_name}/")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise error_type(f"{path} contains an unsafe path component")
    return candidate.as_posix()


def _resolve_relative_file(root: Path, relative: str, root_name: str, error_type) -> Path:
    relative = _safe_relative_path(relative, root_name, relative, error_type)
    unresolved = root / Path(*PurePosixPath(relative).parts)
    if unresolved.is_symlink():
        raise error_type(f"Symbolic links are forbidden at {relative}")
    candidate = unresolved.resolve()
    allowed_root = (root / root_name).resolve()
    if not candidate.is_relative_to(allowed_root):
        raise error_type(f"Path escapes {root_name}/: {relative}")
    if not candidate.is_file() or candidate.is_symlink():
        raise error_type(f"Expected a real file at {relative}")
    return candidate


def _media_type(path: Path) -> str:
    media_type = VIDEO_MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        supported = ", ".join(sorted(VIDEO_MEDIA_TYPES))
        raise InputContractError(
            f"Unsupported ingest file {path.name!r}; expected one video with extension: {supported}"
        )
    return media_type


def _find_single_video(root: Path) -> Path:
    ingest = root / "ingest"
    entries = [entry for entry in ingest.iterdir() if entry.name != ".gitkeep"]
    if len(entries) != 1:
        raise InputContractError(
            f"ingest/ must contain exactly one video file; found {len(entries)} entries"
        )
    source = entries[0]
    if not source.is_file() or source.is_symlink():
        raise InputContractError("The ingest entry must be a real, non-symlink video file")
    if source.stat().st_size <= 0:
        raise InputContractError("The ingest video must not be empty")
    _media_type(source)
    return source


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (normalized or "media")[:60].rstrip("-") or "media"


def _parameters(value: object, error_type=InputContractError) -> dict:
    parameters = _strict_fields(
        value,
        {"silence_threshold_db", "frame_seconds", "hop_seconds", "random_seed"},
        "parameters",
        error_type,
    )
    silence = _number(
        parameters["silence_threshold_db"],
        "parameters.silence_threshold_db",
        error_type,
        minimum=-120.0,
        maximum=0.0,
    )
    frame = _number(
        parameters["frame_seconds"],
        "parameters.frame_seconds",
        error_type,
        minimum=0.000001,
        maximum=10.0,
    )
    hop = _number(
        parameters["hop_seconds"],
        "parameters.hop_seconds",
        error_type,
        minimum=0.000001,
        maximum=10.0,
    )
    if hop > frame:
        raise error_type("parameters.hop_seconds must not exceed frame_seconds")
    seed = _integer(
        parameters["random_seed"],
        "parameters.random_seed",
        error_type,
        minimum=0,
    )
    if seed > 2147483647:
        raise error_type("parameters.random_seed must not exceed 2147483647")
    return {
        "silence_threshold_db": silence,
        "frame_seconds": frame,
        "hop_seconds": hop,
        "random_seed": seed,
    }


def _source_record(source: Path) -> dict:
    return {
        "path": f"ingest/{source.name}",
        "filename": source.name,
        "sha256": sha256_file(source),
        "size_bytes": source.stat().st_size,
        "media_type": _media_type(source),
    }


def _run_id(source_sha256: str, parameters: dict, package_sha256: str) -> str:
    material = {
        "analysis_id": ANALYSIS_ID,
        "package_sha256": package_sha256,
        "parameters": parameters,
        "source_sha256": source_sha256,
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return f"local-{digest[:16]}"


def prepare_analysis_input(
    workspace: str | Path,
    *,
    parameters: dict | None = None,
) -> dict:
    """Hash exactly one local video and write deterministic Wolfram input evidence."""
    layout = initialize_workspace(workspace)
    root = Path(layout["workspace"])
    source_path = _find_single_video(root)
    source = _source_record(source_path)
    normalized_parameters = _parameters(parameters or DEFAULT_PARAMETERS)
    package_sha256 = package_source_hash()
    object_id = f"local-{_slug(source_path.stem)}-{source['sha256'][:12]}"
    run_id = _run_id(source["sha256"], normalized_parameters, package_sha256)

    # A newly prepared valid run invalidates prior canonical/raw success markers.
    # Other generated artifacts may remain for inspection, but cannot be mistaken
    # for a current validated result without result.json.
    for filename in ("result.json", "result.raw.json"):
        candidate = root / "output" / filename
        if candidate.exists():
            if not candidate.is_file() or candidate.is_symlink():
                raise InputContractError(f"output/{filename} must be a real file")
            candidate.unlink()
    repeatability_record = root / "artefacts" / "repeatability.json"
    if repeatability_record.exists():
        if not repeatability_record.is_file() or repeatability_record.is_symlink():
            raise InputContractError("artefacts/repeatability.json must be a real file")
        repeatability_record.unlink()

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "BABELAPHA_LOCAL_SOURCE_V1",
        "canonicalization": CANONICALIZATION,
        "object_id": object_id,
        "run_id": run_id,
        "source": source,
        "events": [
            {
                "sequence": 1,
                "event_type": "SOURCE_DISCOVERED",
                "stage": "ingest",
                "status": "SUCCEEDED",
                "artifact_count": 1,
            },
            {
                "sequence": 2,
                "event_type": "SOURCE_HASH_VERIFIED",
                "stage": "prepare",
                "status": "SUCCEEDED",
                "artifact_count": 1,
            },
        ],
    }
    evidence_path = root / "artefacts" / "source-evidence.json"
    evidence_body = canonical_json_bytes(evidence)
    _atomic_write(evidence_path, evidence_body)

    analysis_input = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "object_id": object_id,
        "run_id": run_id,
        "package_sha256": package_sha256,
        "source": source,
        "evidence": {
            "path": "artefacts/source-evidence.json",
            "sha256": hashlib.sha256(evidence_body).hexdigest(),
        },
        "output_directory": "output",
        "parameters": normalized_parameters,
    }
    input_path = root / "artefacts" / "analysis-input.json"
    _atomic_write_json(input_path, analysis_input)
    return {
        "workspace": str(root),
        "input_path": str(input_path),
        "evidence_path": str(evidence_path),
        "object_id": object_id,
        "run_id": run_id,
        "package_sha256": package_sha256,
        "source_sha256": source["sha256"],
        "evidence_sha256": analysis_input["evidence"]["sha256"],
    }


def _validate_source(value: object, path: str, error_type) -> dict:
    source = _strict_fields(
        value,
        {"path", "filename", "sha256", "size_bytes", "media_type"},
        path,
        error_type,
    )
    relative = _safe_relative_path(source["path"], "ingest", f"{path}.path", error_type)
    filename = _string(source["filename"], f"{path}.filename", error_type)
    if PurePosixPath(relative).name != filename or "/" in filename or "\\" in filename:
        raise error_type(f"{path}.filename must equal the basename of {path}.path")
    _sha256(source["sha256"], f"{path}.sha256", error_type)
    _integer(source["size_bytes"], f"{path}.size_bytes", error_type, minimum=1)
    media_type = _string(source["media_type"], f"{path}.media_type", error_type)
    expected_type = VIDEO_MEDIA_TYPES.get(Path(filename).suffix.lower())
    if expected_type is None or media_type != expected_type:
        raise error_type(f"{path}.media_type does not match the supported video extension")
    return source


def _validate_evidence_document(evidence: dict, analysis_input: dict) -> None:
    _strict_fields(
        evidence,
        {
            "schema_version",
            "evidence_type",
            "canonicalization",
            "object_id",
            "run_id",
            "source",
            "events",
        },
        "source evidence",
        IntegrityError,
    )
    if evidence["schema_version"] != SCHEMA_VERSION:
        raise IntegrityError("Unsupported source evidence schema version")
    if evidence["evidence_type"] != "BABELAPHA_LOCAL_SOURCE_V1":
        raise IntegrityError("Unsupported local source evidence type")
    if evidence["canonicalization"] != CANONICALIZATION:
        raise IntegrityError("Unsupported source evidence canonicalization")
    for field in ("object_id", "run_id", "source"):
        if evidence[field] != analysis_input[field]:
            raise IntegrityError(f"Source evidence {field} differs from analysis input")
    events = evidence["events"]
    expected_events = [
        (1, "SOURCE_DISCOVERED", "ingest"),
        (2, "SOURCE_HASH_VERIFIED", "prepare"),
    ]
    if not isinstance(events, list) or len(events) != len(expected_events):
        raise IntegrityError("Source evidence must contain the two local trust events")
    for index, (event, expected) in enumerate(zip(events, expected_events)):
        event = _strict_fields(
            event,
            {"sequence", "event_type", "stage", "status", "artifact_count"},
            f"source evidence.events[{index}]",
            IntegrityError,
        )
        actual = (event["sequence"], event["event_type"], event["stage"])
        if actual != expected or event["status"] != "SUCCEEDED" or event["artifact_count"] != 1:
            raise IntegrityError(f"Source evidence.events[{index}] is not canonical")


def validate_analysis_input(workspace: str | Path, input_path: Path | None = None) -> dict:
    """Re-prove the prepared input, source bytes, and local evidence bytes."""
    root = _workspace_path(workspace)
    for name in ("ingest", "artefacts", "output"):
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            raise InputContractError(f"Workspace {name}/ must be a real directory")
    unresolved_path = (
        Path(input_path) if input_path is not None else root / "artefacts" / "analysis-input.json"
    )
    if unresolved_path.is_symlink():
        raise InputContractError("Analysis input must not be a symbolic link")
    path = unresolved_path.resolve()
    allowed = (root / "artefacts").resolve()
    if not path.is_relative_to(allowed) or path.is_symlink():
        raise InputContractError("Analysis input must be a real file below artefacts/")
    analysis_input = load_json(path, InputContractError)
    if path.read_bytes() != canonical_json_bytes(analysis_input):
        raise InputContractError("analysis-input.json is not canonical sorted/indented JSON")
    _strict_fields(
        analysis_input,
        {
            "schema_version",
            "analysis_id",
            "object_id",
            "run_id",
            "package_sha256",
            "source",
            "evidence",
            "output_directory",
            "parameters",
        },
        "analysis input",
        InputContractError,
    )
    if analysis_input["schema_version"] != SCHEMA_VERSION:
        raise InputContractError("Unsupported analysis input schema version")
    if analysis_input["analysis_id"] != ANALYSIS_ID:
        raise InputContractError("Unsupported analysis ID")
    object_id = _string(analysis_input["object_id"], "object_id", InputContractError)
    if not object_id.startswith("local-") or not _IDENTIFIER_RE.fullmatch(object_id):
        raise InputContractError("object_id is not a canonical local identifier")
    run_id = _string(analysis_input["run_id"], "run_id", InputContractError)
    if not re.fullmatch(r"local-[a-f0-9]{16}", run_id):
        raise InputContractError("run_id is not a canonical local run identifier")
    expected_package_sha256 = _sha256(
        analysis_input["package_sha256"], "package_sha256", InputContractError
    )
    if package_source_hash() != expected_package_sha256:
        raise IntegrityError("Wolfram package SHA-256 differs from analysis input")
    source = _validate_source(analysis_input["source"], "source", InputContractError)
    parameters = _parameters(analysis_input["parameters"])
    if analysis_input["output_directory"] != "output":
        raise InputContractError("output_directory must be the local output directory")

    source_path = _resolve_relative_file(root, source["path"], "ingest", IntegrityError)
    if source_path.stat().st_size != source["size_bytes"]:
        raise IntegrityError("Ingest video size differs from prepared source evidence")
    if sha256_file(source_path) != source["sha256"]:
        raise IntegrityError("Ingest video SHA-256 differs from prepared source evidence")
    if analysis_input["run_id"] != _run_id(
        source["sha256"], parameters, expected_package_sha256
    ):
        raise IntegrityError("run_id does not match source and parameter identity")
    expected_object_id = f"local-{_slug(source_path.stem)}-{source['sha256'][:12]}"
    if analysis_input["object_id"] != expected_object_id:
        raise IntegrityError("object_id does not match source identity")

    evidence_ref = _strict_fields(
        analysis_input["evidence"],
        {"path", "sha256"},
        "evidence",
        InputContractError,
    )
    evidence_relative = _safe_relative_path(
        evidence_ref["path"], "artefacts", "evidence.path", InputContractError
    )
    if evidence_relative != "artefacts/source-evidence.json":
        raise InputContractError("evidence.path must identify source-evidence.json")
    expected_evidence_sha = _sha256(
        evidence_ref["sha256"], "evidence.sha256", InputContractError
    )
    evidence_path = _resolve_relative_file(root, evidence_relative, "artefacts", IntegrityError)
    evidence_body = evidence_path.read_bytes()
    if hashlib.sha256(evidence_body).hexdigest() != expected_evidence_sha:
        raise IntegrityError("Local source evidence SHA-256 differs from analysis input")
    evidence = load_json(evidence_path, IntegrityError)
    if evidence_body != canonical_json_bytes(evidence):
        raise IntegrityError("Local source evidence bytes are not canonical")
    _validate_evidence_document(evidence, analysis_input)
    return analysis_input


def _validate_intervals(value: object, path: str, duration: float) -> None:
    if not isinstance(value, list):
        raise ResultContractError(f"{path} must be an array")
    previous_end = 0.0
    for index, interval in enumerate(value):
        if not isinstance(interval, list) or len(interval) != 2:
            raise ResultContractError(f"{path}[{index}] must be [start, end]")
        start = _number(
            interval[0], f"{path}[{index}][0]", ResultContractError, minimum=0.0
        )
        end = _number(
            interval[1], f"{path}[{index}][1]", ResultContractError, minimum=0.0
        )
        if end <= start:
            raise ResultContractError(f"{path}[{index}] must have positive duration")
        if start < previous_end:
            raise ResultContractError(f"{path} must be sorted and non-overlapping")
        if end > duration + 1e-9:
            raise ResultContractError(f"{path}[{index}] exceeds media duration")
        previous_end = end


def _validate_summary(value: object, path: str, *, nullable: bool = False) -> None:
    summary = _strict_fields(
        value,
        {"minimum", "mean", "maximum"},
        path,
        ResultContractError,
    )
    values = [
        _number(
            summary[field],
            f"{path}.{field}",
            ResultContractError,
            minimum=0.0,
            nullable=nullable,
        )
        for field in ("minimum", "mean", "maximum")
    ]
    if all(item is None for item in values):
        return
    if any(item is None for item in values):
        raise ResultContractError(f"{path} must be entirely numeric or entirely null")
    if not values[0] <= values[1] <= values[2]:
        raise ResultContractError(f"{path} must satisfy minimum <= mean <= maximum")


def _validate_string_array(
    value: object, path: str, *, minimum: int = 0, unique: bool = True
) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ResultContractError(f"{path} must contain at least {minimum} strings")
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", ResultContractError)
    if unique and len(set(value)) != len(value):
        raise ResultContractError(f"{path} must not contain duplicates")
    return value


def _validate_capabilities(value: object) -> None:
    capabilities = _strict_fields(
        value,
        CAPABILITY_KEYS,
        "capabilities",
        ResultContractError,
    )
    for name, raw_capability in capabilities.items():
        capability = _strict_fields(
            raw_capability,
            {"status", "reason"},
            f"capabilities.{name}",
            ResultContractError,
        )
        status = _string(
            capability["status"], f"capabilities.{name}.status", ResultContractError
        )
        reason = _string(
            capability["reason"],
            f"capabilities.{name}.reason",
            ResultContractError,
            nonempty=False,
        )
        if status not in CAPABILITY_STATUSES:
            raise ResultContractError(f"capabilities.{name}.status is unsupported")
        if status == "USED" and reason:
            raise ResultContractError(f"capabilities.{name}.reason must be empty when USED")
        if status != "USED" and not reason:
            raise ResultContractError(
                f"capabilities.{name}.reason must explain why the capability was not used"
            )
    required_used = {
        "video_import",
        "frame_analysis",
        "time_series",
        "event_series",
        "tabular",
        "notebook_export",
    }
    unavailable = sorted(
        name for name in required_used if capabilities[name]["status"] != "USED"
    )
    if unavailable:
        raise ResultContractError(
            f"Successful analysis requires core Mathematica capabilities: {unavailable}"
        )


def _validate_video_measurements(value: object, duration: float) -> None:
    video = _strict_fields(
        value,
        {
            "duration_seconds",
            "frame_count_sampled",
            "frame_dimensions",
            "brightness",
            "mean_rgb",
            "motion",
        },
        "measurements.video",
        ResultContractError,
    )
    video_duration = _number(
        video["duration_seconds"],
        "measurements.video.duration_seconds",
        ResultContractError,
        minimum=0.000001,
    )
    if not math.isclose(video_duration, duration, rel_tol=1e-9, abs_tol=1e-9):
        raise ResultContractError("Video duration differs from overall duration")
    frame_count = _integer(
        video["frame_count_sampled"],
        "measurements.video.frame_count_sampled",
        ResultContractError,
        minimum=1,
    )
    dimensions = video["frame_dimensions"]
    if not isinstance(dimensions, list) or len(dimensions) != 2:
        raise ResultContractError("measurements.video.frame_dimensions must be [width, height]")
    for index, value in enumerate(dimensions):
        _integer(
            value,
            f"measurements.video.frame_dimensions[{index}]",
            ResultContractError,
            minimum=1,
        )
    _validate_summary(video["brightness"], "measurements.video.brightness")
    for field in ("minimum", "mean", "maximum"):
        if video["brightness"][field] > 1.0:
            raise ResultContractError("measurements.video.brightness values must not exceed 1")

    mean_rgb = _strict_fields(
        video["mean_rgb"],
        {"red", "green", "blue"},
        "measurements.video.mean_rgb",
        ResultContractError,
    )
    for component in ("red", "green", "blue"):
        _number(
            mean_rgb[component],
            f"measurements.video.mean_rgb.{component}",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
        )

    motion = _strict_fields(
        video["motion"],
        {"method", "transition_count", "mean", "maximum"},
        "measurements.video.motion",
        ResultContractError,
    )
    if motion["method"] != "mean-absolute-grayscale-frame-difference":
        raise ResultContractError("measurements.video.motion.method is unsupported")
    transitions = _integer(
        motion["transition_count"],
        "measurements.video.motion.transition_count",
        ResultContractError,
        minimum=0,
    )
    mean = _number(
        motion["mean"],
        "measurements.video.motion.mean",
        ResultContractError,
        minimum=0.0,
        maximum=1.0,
        nullable=True,
    )
    maximum = _number(
        motion["maximum"],
        "measurements.video.motion.maximum",
        ResultContractError,
        minimum=0.0,
        maximum=1.0,
        nullable=True,
    )
    if transitions == 0:
        if mean is not None or maximum is not None or frame_count >= 2:
            raise ResultContractError("Zero motion transitions require one sampled frame and null summaries")
    elif mean is None or maximum is None or mean > maximum:
        raise ResultContractError("Motion summaries must be finite and ordered when transitions exist")
    if transitions != frame_count - 1:
        raise ResultContractError("Motion transition count must equal sampled frame count minus one")


def _validate_measurements(value: object, capabilities: dict) -> None:
    measurements = _strict_fields(
        value,
        {
            "duration_seconds",
            "audio_duration_seconds",
            "sample_rate_hz",
            "channel_count",
            "rms_amplitude",
            "peak_amplitude",
            "integrated_loudness_lufs",
            "audible_intervals_seconds",
            "silence_intervals_seconds",
            "spectral_centroid_hz",
            "measurement_series",
            "evidence_events",
            "tabular_summary",
            "video",
        },
        "measurements",
        ResultContractError,
    )
    duration = _number(
        measurements["duration_seconds"],
        "measurements.duration_seconds",
        ResultContractError,
        minimum=0.000001,
    )
    audio_available = capabilities["audio_track"]["status"] == "USED"
    nullable_audio = not audio_available
    audio_duration = _number(
        measurements["audio_duration_seconds"],
        "measurements.audio_duration_seconds",
        ResultContractError,
        minimum=0.000001,
        nullable=nullable_audio,
    )
    if nullable_audio and audio_duration is not None:
        raise ResultContractError("Unavailable audio requires a null audio duration")
    if audio_available and audio_duration is None:
        raise ResultContractError("Available audio requires a positive audio duration")
    sample_rate = measurements["sample_rate_hz"]
    channels = measurements["channel_count"]
    if nullable_audio:
        if sample_rate is not None or channels is not None:
            raise ResultContractError("Unavailable audio requires null sample rate and channel count")
    else:
        _integer(sample_rate, "measurements.sample_rate_hz", ResultContractError, minimum=1)
        _integer(channels, "measurements.channel_count", ResultContractError, minimum=1)
    rms = _number(
        measurements["rms_amplitude"],
        "measurements.rms_amplitude",
        ResultContractError,
        minimum=0.0,
        nullable=nullable_audio,
    )
    peak = _number(
        measurements["peak_amplitude"],
        "measurements.peak_amplitude",
        ResultContractError,
        minimum=0.0,
        nullable=nullable_audio,
    )
    loudness = _number(
        measurements["integrated_loudness_lufs"],
        "measurements.integrated_loudness_lufs",
        ResultContractError,
        nullable=True,
    )
    if nullable_audio and any(value is not None for value in (rms, peak, loudness)):
        raise ResultContractError("Unavailable audio requires null audio measurements")
    if not nullable_audio and rms is not None and peak is not None and rms > peak + 1e-12:
        raise ResultContractError("RMS amplitude must not exceed peak amplitude")
    _validate_intervals(
        measurements["audible_intervals_seconds"],
        "measurements.audible_intervals_seconds",
        audio_duration if audio_duration is not None else duration,
    )
    _validate_intervals(
        measurements["silence_intervals_seconds"],
        "measurements.silence_intervals_seconds",
        audio_duration if audio_duration is not None else duration,
    )
    if nullable_audio and (
        measurements["audible_intervals_seconds"]
        or measurements["silence_intervals_seconds"]
    ):
        raise ResultContractError("Unavailable audio requires empty interval arrays")
    _validate_summary(
        measurements["spectral_centroid_hz"],
        "measurements.spectral_centroid_hz",
        nullable=nullable_audio,
    )
    if nullable_audio and any(
        value is not None for value in measurements["spectral_centroid_hz"].values()
    ):
        raise ResultContractError("Unavailable audio requires a null spectral summary")

    series = _strict_fields(
        measurements["measurement_series"],
        {"time_count", "component_names"},
        "measurements.measurement_series",
        ResultContractError,
    )
    time_count = _integer(
        series["time_count"],
        "measurements.measurement_series.time_count",
        ResultContractError,
        minimum=0,
    )
    component_names = _validate_string_array(
        series["component_names"],
        "measurements.measurement_series.component_names",
        minimum=0 if nullable_audio else 1,
    )
    if nullable_audio and (time_count != 0 or component_names):
        raise ResultContractError("Unavailable audio requires an empty measurement series")
    if audio_available and time_count < 1:
        raise ResultContractError("Available audio requires a non-empty measurement series")
    if audio_available and set(component_names) != {
        "rms_amplitude",
        "spectral_centroid_hz",
    }:
        raise ResultContractError("Audio measurement series has unexpected components")

    events = _strict_fields(
        measurements["evidence_events"],
        {"event_count", "event_types"},
        "measurements.evidence_events",
        ResultContractError,
    )
    event_count = _integer(
        events["event_count"],
        "measurements.evidence_events.event_count",
        ResultContractError,
        minimum=2,
    )
    event_types = _validate_string_array(
        events["event_types"],
        "measurements.evidence_events.event_types",
        minimum=2,
    )
    if event_count != len(event_types):
        raise ResultContractError("Evidence event count differs from unique event types")
    if set(event_types) != {"SOURCE_DISCOVERED", "SOURCE_HASH_VERIFIED"}:
        raise ResultContractError("Evidence event types differ from verified local evidence")

    tabular = _strict_fields(
        measurements["tabular_summary"],
        {"row_count", "column_names"},
        "measurements.tabular_summary",
        ResultContractError,
    )
    row_count = _integer(
        tabular["row_count"],
        "measurements.tabular_summary.row_count",
        ResultContractError,
        minimum=2,
    )
    column_names = _validate_string_array(
        tabular["column_names"],
        "measurements.tabular_summary.column_names",
        minimum=1,
    )
    if row_count != event_count:
        raise ResultContractError("Tabular row count differs from evidence event count")
    if set(column_names) != {"sequence", "event_type", "stage", "status", "artifact_count"}:
        raise ResultContractError("Tabular columns differ from local evidence fields")
    _validate_video_measurements(measurements["video"], duration)


def _validate_outputs(root: Path, value: object) -> None:
    if not isinstance(value, list) or len(value) != len(EXPECTED_OUTPUT_MEDIA_TYPES):
        raise ResultContractError(
            "outputs must list each required portable report, plot, and notebook exactly once"
        )
    seen = set()
    for index, raw_output in enumerate(value):
        output = _strict_fields(
            raw_output,
            {"path", "media_type", "sha256", "size_bytes"},
            f"outputs[{index}]",
            ResultContractError,
        )
        path = _string(output["path"], f"outputs[{index}].path", ResultContractError)
        if "\\" in path:
            raise ResultContractError(f"outputs[{index}].path must use forward slashes")
        relative = PurePosixPath(path)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name != path:
            raise ResultContractError(f"outputs[{index}].path must be a direct child of output/")
        if path in seen:
            raise ResultContractError(f"outputs repeats path {path!r}")
        seen.add(path)
        expected_media_type = EXPECTED_OUTPUT_MEDIA_TYPES.get(path)
        if output["media_type"] != expected_media_type:
            raise ResultContractError(f"outputs[{index}] has an unexpected path or media type")
        expected_sha = _sha256(
            output["sha256"], f"outputs[{index}].sha256", ResultContractError
        )
        expected_size = _integer(
            output["size_bytes"],
            f"outputs[{index}].size_bytes",
            ResultContractError,
            minimum=1,
        )
        output_path = _resolve_relative_file(
            root, f"output/{path}", "output", ResultContractError
        )
        if output_path.stat().st_size != expected_size:
            raise IntegrityError(f"Output size differs for output/{path}")
        if sha256_file(output_path) != expected_sha:
            raise IntegrityError(f"Output SHA-256 differs for output/{path}")
    if seen != set(EXPECTED_OUTPUT_MEDIA_TYPES):
        raise ResultContractError("outputs do not contain the exact required artifact set")


def validate_result(
    workspace: str | Path,
    *,
    raw_result_path: Path | None = None,
    input_path: Path | None = None,
) -> dict:
    """Validate Mathematica's raw result and atomically publish canonical JSON."""
    root = _workspace_path(workspace)
    analysis_input = validate_analysis_input(root, input_path)
    unresolved_raw_path = (
        Path(raw_result_path)
        if raw_result_path is not None
        else root / "output" / "result.raw.json"
    )
    if unresolved_raw_path.is_symlink():
        raise ResultContractError("Raw result must not be a symbolic link")
    raw_path = unresolved_raw_path.resolve()
    if not raw_path.is_relative_to((root / "output").resolve()) or raw_path.is_symlink():
        raise ResultContractError("Raw result must be a real file below output/")
    result = load_json(raw_path, ResultContractError)
    _strict_fields(
        result,
        {
            "schema_version",
            "analysis_id",
            "object_id",
            "run_id",
            "processor",
            "source",
            "evidence",
            "parameters",
            "capabilities",
            "measurements",
            "provenance_summary",
            "outputs",
        },
        "result",
        ResultContractError,
    )
    for field in ("schema_version", "analysis_id", "object_id", "run_id", "source", "evidence", "parameters"):
        if result[field] != analysis_input[field]:
            raise IntegrityError(f"Result {field} differs from the verified analysis input")

    processor = _strict_fields(
        result["processor"],
        {"name", "wolfram_version", "system_id", "package_sha256", "network_mode"},
        "processor",
        ResultContractError,
    )
    if processor["name"] != "BabelaphaAnalysis":
        raise ResultContractError("processor.name is unsupported")
    version = _string(processor["wolfram_version"], "processor.wolfram_version", ResultContractError)
    version_match = re.match(r"^(\d+)\.", version)
    if version_match is None or int(version_match.group(1)) < 15:
        raise ResultContractError("processor.wolfram_version must identify Wolfram 15 or newer")
    _string(processor["system_id"], "processor.system_id", ResultContractError)
    processor_package_sha256 = _sha256(
        processor["package_sha256"],
        "processor.package_sha256",
        ResultContractError,
    )
    if processor_package_sha256 != analysis_input["package_sha256"]:
        raise IntegrityError("Processor package SHA-256 differs from verified analysis input")
    if package_source_hash() != processor_package_sha256:
        raise IntegrityError("Processor package SHA-256 differs from current package sources")
    if processor["network_mode"] != "disabled":
        raise ResultContractError("processor.network_mode must be disabled")

    _validate_capabilities(result["capabilities"])
    _validate_measurements(result["measurements"], result["capabilities"])
    provenance = _strict_fields(
        result["provenance_summary"],
        {"task_count", "artifact_count", "integrity_conflict_count", "evidence_sha256"},
        "provenance_summary",
        ResultContractError,
    )
    if provenance["task_count"] != 2 or provenance["artifact_count"] != 1:
        raise ResultContractError("Provenance counts differ from the local source evidence")
    if provenance["integrity_conflict_count"] != 0:
        raise IntegrityError("Mathematica reported a provenance integrity conflict")
    if provenance["evidence_sha256"] != analysis_input["evidence"]["sha256"]:
        raise IntegrityError("Provenance evidence SHA-256 differs from verified input")
    _validate_outputs(root, result["outputs"])

    result_path = root / "output" / "result.json"
    result_body = canonical_json_bytes(result)
    _atomic_write(result_path, result_body)
    return {
        "workspace": str(root),
        "result_path": str(result_path),
        "result_sha256": hashlib.sha256(result_body).hexdigest(),
        "output_count": len(result["outputs"]),
        "object_id": result["object_id"],
        "run_id": result["run_id"],
    }


def write_deterministic_test_wav(path: Path) -> dict:
    """Write a stable PCM fixture for unit tests only; prepare accepts video only."""
    sample_rate = 8000
    sample_count = sample_rate
    frames = bytearray()
    for index in range(sample_count):
        # A deterministic square wave avoids platform-dependent trig rounding.
        amplitude = 0 if index < sample_rate // 4 else (4096 if (index // 10) % 2 else -4096)
        frames.extend(struct.pack("<h", amplitude))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(frames))
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and validate the local Mathematica media prototype trust boundary."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="Create the local prototype directories")
    initialize.add_argument("--workspace", default="Local-prototype")

    prepare = commands.add_parser("prepare", help="Hash one ingest video and write analysis input")
    prepare.add_argument("--workspace", default="Local-prototype")
    prepare.add_argument("--silence-threshold-db", type=float, default=-40.0)
    prepare.add_argument("--frame-seconds", type=float, default=0.04)
    prepare.add_argument("--hop-seconds", type=float, default=0.02)
    prepare.add_argument("--random-seed", type=int, default=20260916)

    validate = commands.add_parser("validate", help="Verify and canonicalize result.raw.json")
    validate.add_argument("--workspace", default="Local-prototype")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            details = initialize_workspace(args.workspace)
            status = "INITIALIZED"
        elif args.command == "prepare":
            details = prepare_analysis_input(
                args.workspace,
                parameters={
                    "silence_threshold_db": args.silence_threshold_db,
                    "frame_seconds": args.frame_seconds,
                    "hop_seconds": args.hop_seconds,
                    "random_seed": args.random_seed,
                },
            )
            status = "PREPARED"
        else:
            details = validate_result(args.workspace)
            status = "VALIDATED"
    except BoundaryError as exc:
        print(
            json.dumps(
                {"status": "FAILED", "reason_code": exc.reason_code, "message": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return exc.exit_code
    print(json.dumps({"status": status, **details}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
