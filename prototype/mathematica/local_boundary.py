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


SCHEMA_VERSION = "2.0.0"
SOURCE_EVIDENCE_VERSION = "2.0.0"
ANALYSIS_ID = "mathematica-local-media-lab-v2"
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

TRANSCRIPT_MEDIA_TYPES = {
    ".txt": ("text/plain", "txt"),
    ".srt": ("application/x-subrip", "srt"),
    ".vtt": ("text/vtt", "vtt"),
}

TRANSCRIPT_MODES = {"automatic", "prefer_sidecar", "sidecar", "disabled"}

WHISPER_MODEL_IDENTITY = {
    "repository_resource_name": "Whisper-V1 Nets",
    "resource_uuid": "5211d691-293f-417d-a19f-f1e5faef3fb7",
    "resource_version": "1.0.0",
    "size": "Tiny",
    "target_device": "CPU",
    "network_mode": "disabled",
    "identity_sha256": "49329aeb256c668a81019ddd1ca12b4b04d781c0a855c63cacfbcc317f2d13b9",
}

WHISPER_ARTIFACTS = {
    "audio_encoder": {
        "content_element": "EvaluationNet:tiny_encoder",
        "sha256": "0c42ff9e0c142bf5f8badf35d9ce337ea9b4d4edce761b31caaebe53c25a464c",
        "size_bytes": 32934064,
    },
    "text_decoder": {
        "content_element": "EvaluationNet:tiny_decoder",
        "sha256": "4d39de7df517ac91679b4daa9bd359dba0e85a1f9748699090c1c946a7ec4f9a",
        "size_bytes": 197918640,
    },
    "labels": {
        "content_element": "Labels",
        "sha256": "d3c09f659b7ef46cfaae621574a751fcac71656c6436e997f71129006ccc16ef",
        "size_bytes": 437955,
    },
}

CAPABILITY_KEYS = {
    "video_import",
    "audio_track",
    "video_summary_plot",
    "frame_analysis",
    "color_analysis",
    "motion_analysis",
    "sound_analysis",
    "transcript_analysis",
    "cross_modal_analysis",
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
    for name in (
        "ingest",
        "transcripts",
        "models",
        "artefacts",
        "output",
        "logs",
        "work",
    ):
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
    entries = [
        entry for entry in ingest.iterdir() if entry.name not in {".gitignore", ".gitkeep"}
    ]
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


def _find_optional_transcript(root: Path, source: Path) -> Path | None:
    transcript_directory = root / "transcripts"
    entries = [
        entry
        for entry in transcript_directory.iterdir()
        if entry.name not in {".gitignore", ".gitkeep"}
    ]
    if not entries:
        return None
    supported = [entry for entry in entries if entry.suffix.lower() in TRANSCRIPT_MEDIA_TYPES]
    if len(supported) != len(entries):
        unsupported = sorted(entry.name for entry in entries if entry not in supported)
        raise InputContractError(
            "transcripts/ contains unsupported entries: " + ", ".join(unsupported)
        )
    matching = [entry for entry in supported if entry.stem.casefold() == source.stem.casefold()]
    selected = matching if matching else supported
    if len(selected) != 1:
        raise InputContractError(
            "transcripts/ must contain at most one sidecar, or exactly one whose basename "
            f"matches {source.stem!r}; found {len(supported)} supported files"
        )
    sidecar = selected[0]
    if not sidecar.is_file() or sidecar.is_symlink():
        raise InputContractError("The transcript sidecar must be a real, non-symlink file")
    if sidecar.stat().st_size <= 0:
        raise InputContractError("The transcript sidecar must not be empty")
    return sidecar


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


def _transcript_record(sidecar: Path | None) -> dict | None:
    if sidecar is None:
        return None
    media_type, transcript_format = TRANSCRIPT_MEDIA_TYPES[sidecar.suffix.lower()]
    return {
        "path": f"transcripts/{sidecar.name}",
        "filename": sidecar.name,
        "sha256": sha256_file(sidecar),
        "size_bytes": sidecar.stat().st_size,
        "media_type": media_type,
        "format": transcript_format,
    }


def _run_id(
    source_sha256: str,
    parameters: dict,
    package_sha256: str,
    transcript: dict,
) -> str:
    material = {
        "analysis_id": ANALYSIS_ID,
        "package_sha256": package_sha256,
        "parameters": parameters,
        "source_sha256": source_sha256,
        "transcript": transcript,
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return f"local-{digest[:16]}"


def prepare_analysis_input(
    workspace: str | Path,
    *,
    parameters: dict | None = None,
    transcript_mode: str = "prefer_sidecar",
) -> dict:
    """Hash exactly one local video and write deterministic Wolfram input evidence."""
    layout = initialize_workspace(workspace)
    root = Path(layout["workspace"])
    source_path = _find_single_video(root)
    source = _source_record(source_path)
    transcript_mode = transcript_mode.casefold()
    if transcript_mode not in TRANSCRIPT_MODES:
        raise InputContractError(
            f"Unsupported transcript mode {transcript_mode!r}; expected one of "
            + ", ".join(sorted(TRANSCRIPT_MODES))
        )
    sidecar_path = _find_optional_transcript(root, source_path)
    sidecar = _transcript_record(sidecar_path)
    if transcript_mode == "sidecar" and sidecar is None:
        raise InputContractError(
            "Transcript mode 'sidecar' requires one .txt, .srt, or .vtt file in transcripts/"
        )
    if transcript_mode == "disabled" and sidecar is not None:
        raise InputContractError(
            "Transcript mode 'disabled' requires transcripts/ to contain no sidecar"
        )
    transcript = {"mode": transcript_mode, "sidecar": sidecar}
    normalized_parameters = _parameters(parameters or DEFAULT_PARAMETERS)
    package_sha256 = package_source_hash()
    object_id = f"local-{_slug(source_path.stem)}-{source['sha256'][:12]}"
    run_id = _run_id(source["sha256"], normalized_parameters, package_sha256, transcript)

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

    evidence_events = [
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
    ]
    if sidecar is not None:
        evidence_events.extend(
            [
                {
                    "sequence": 3,
                    "event_type": "TRANSCRIPT_SOURCE_DISCOVERED",
                    "stage": "transcripts",
                    "status": "SUCCEEDED",
                    "artifact_count": 2,
                },
                {
                    "sequence": 4,
                    "event_type": "TRANSCRIPT_SOURCE_HASH_VERIFIED",
                    "stage": "prepare",
                    "status": "SUCCEEDED",
                    "artifact_count": 2,
                },
            ]
        )

    evidence = {
        "schema_version": SOURCE_EVIDENCE_VERSION,
        "evidence_type": "BABELAPHA_LOCAL_SOURCE_V2",
        "canonicalization": CANONICALIZATION,
        "object_id": object_id,
        "run_id": run_id,
        "source": source,
        "transcript_sidecar": sidecar,
        "events": evidence_events,
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
        "transcript": transcript,
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
        "transcript_sha256": None if sidecar is None else sidecar["sha256"],
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


def _validate_transcript_sidecar(value: object, path: str, error_type) -> dict | None:
    if value is None:
        return None
    sidecar = _strict_fields(
        value,
        {"path", "filename", "sha256", "size_bytes", "media_type", "format"},
        path,
        error_type,
    )
    relative = _safe_relative_path(
        sidecar["path"], "transcripts", f"{path}.path", error_type
    )
    filename = _string(sidecar["filename"], f"{path}.filename", error_type)
    if PurePosixPath(relative).name != filename or "/" in filename or "\\" in filename:
        raise error_type(f"{path}.filename must equal the basename of {path}.path")
    _sha256(sidecar["sha256"], f"{path}.sha256", error_type)
    _integer(sidecar["size_bytes"], f"{path}.size_bytes", error_type, minimum=1)
    expected = TRANSCRIPT_MEDIA_TYPES.get(Path(filename).suffix.lower())
    if expected is None:
        raise error_type(f"{path} uses an unsupported transcript extension")
    media_type = _string(sidecar["media_type"], f"{path}.media_type", error_type)
    transcript_format = _string(sidecar["format"], f"{path}.format", error_type)
    if (media_type, transcript_format) != expected:
        raise error_type(f"{path} media type or format does not match its extension")
    return sidecar


def _validate_transcript_config(value: object, error_type=InputContractError) -> dict:
    transcript = _strict_fields(value, {"mode", "sidecar"}, "transcript", error_type)
    mode = _string(transcript["mode"], "transcript.mode", error_type)
    if mode not in TRANSCRIPT_MODES:
        raise error_type("transcript.mode is unsupported")
    sidecar = _validate_transcript_sidecar(
        transcript["sidecar"], "transcript.sidecar", error_type
    )
    if mode == "sidecar" and sidecar is None:
        raise error_type("transcript.mode sidecar requires transcript.sidecar")
    if mode == "disabled" and sidecar is not None:
        raise error_type("transcript.mode disabled requires a null sidecar")
    return {"mode": mode, "sidecar": sidecar}


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
            "transcript_sidecar",
            "events",
        },
        "source evidence",
        IntegrityError,
    )
    if evidence["schema_version"] != SOURCE_EVIDENCE_VERSION:
        raise IntegrityError("Unsupported source evidence schema version")
    if evidence["evidence_type"] != "BABELAPHA_LOCAL_SOURCE_V2":
        raise IntegrityError("Unsupported local source evidence type")
    if evidence["canonicalization"] != CANONICALIZATION:
        raise IntegrityError("Unsupported source evidence canonicalization")
    for field in ("object_id", "run_id", "source"):
        if evidence[field] != analysis_input[field]:
            raise IntegrityError(f"Source evidence {field} differs from analysis input")
    if evidence["transcript_sidecar"] != analysis_input["transcript"]["sidecar"]:
        raise IntegrityError("Source evidence transcript sidecar differs from analysis input")
    events = evidence["events"]
    expected_events = [
        (1, "SOURCE_DISCOVERED", "ingest", 1),
        (2, "SOURCE_HASH_VERIFIED", "prepare", 1),
    ]
    if analysis_input["transcript"]["sidecar"] is not None:
        expected_events.extend(
            [
                (3, "TRANSCRIPT_SOURCE_DISCOVERED", "transcripts", 2),
                (4, "TRANSCRIPT_SOURCE_HASH_VERIFIED", "prepare", 2),
            ]
        )
    if not isinstance(events, list) or len(events) != len(expected_events):
        raise IntegrityError("Source evidence does not contain the expected local trust events")
    for index, (event, expected) in enumerate(zip(events, expected_events)):
        event = _strict_fields(
            event,
            {"sequence", "event_type", "stage", "status", "artifact_count"},
            f"source evidence.events[{index}]",
            IntegrityError,
        )
        actual = (
            event["sequence"],
            event["event_type"],
            event["stage"],
            event["artifact_count"],
        )
        if actual != expected or event["status"] != "SUCCEEDED":
            raise IntegrityError(f"Source evidence.events[{index}] is not canonical")


def validate_analysis_input(workspace: str | Path, input_path: Path | None = None) -> dict:
    """Re-prove the prepared input, source bytes, and local evidence bytes."""
    root = _workspace_path(workspace)
    for name in ("ingest", "transcripts", "models", "artefacts", "output"):
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
            "transcript",
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
    transcript = _validate_transcript_config(analysis_input["transcript"])
    parameters = _parameters(analysis_input["parameters"])
    if analysis_input["output_directory"] != "output":
        raise InputContractError("output_directory must be the local output directory")

    source_path = _resolve_relative_file(root, source["path"], "ingest", IntegrityError)
    if source_path.stat().st_size != source["size_bytes"]:
        raise IntegrityError("Ingest video size differs from prepared source evidence")
    if sha256_file(source_path) != source["sha256"]:
        raise IntegrityError("Ingest video SHA-256 differs from prepared source evidence")
    sidecar = transcript["sidecar"]
    if sidecar is not None:
        sidecar_path = _resolve_relative_file(
            root, sidecar["path"], "transcripts", IntegrityError
        )
        if sidecar_path.stat().st_size != sidecar["size_bytes"]:
            raise IntegrityError("Transcript sidecar size differs from prepared evidence")
        if sha256_file(sidecar_path) != sidecar["sha256"]:
            raise IntegrityError("Transcript sidecar SHA-256 differs from prepared evidence")
    if analysis_input["run_id"] != _run_id(
        source["sha256"], parameters, expected_package_sha256, transcript
    ):
        raise IntegrityError(
            "run_id does not match source, transcript, parameter, and package identity"
        )
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


def _validate_runtime_manifest(root: Path, processor: dict, analysis_input: dict) -> None:
    path = root / "artefacts" / "runtime.json"
    if path.is_symlink() or not path.is_file():
        raise ResultContractError(
            "artefacts/runtime.json is required to bind the independently probed Wolfram runtime"
        )
    runtime = load_json(path, ResultContractError)
    runtime = _strict_fields(
        runtime,
        {
            "schema_version",
            "recorded_at",
            "local_only",
            "workspace",
            "source_path",
            "analysis_id",
            "run_id",
            "package_sha256",
            "git_commit",
            "git_worktree_clean",
            "git_status_entry_count",
            "wolfram",
            "python",
            "analysis_parameters",
            "speech_model_cache_requested",
            "repeatability_requested",
        },
        "runtime manifest",
        ResultContractError,
    )
    if runtime["schema_version"] != SCHEMA_VERSION or runtime["local_only"] is not True:
        raise ResultContractError("runtime manifest must describe this local v2 workflow")
    _string(runtime["recorded_at"], "runtime manifest.recorded_at", ResultContractError)
    workspace = _string(runtime["workspace"], "runtime manifest.workspace", ResultContractError)
    source_path = _string(
        runtime["source_path"], "runtime manifest.source_path", ResultContractError
    )
    if Path(workspace).resolve() != root.resolve():
        raise IntegrityError("Runtime manifest workspace differs from the validated workspace")
    expected_source = (root / analysis_input["source"]["path"]).resolve()
    if Path(source_path).resolve() != expected_source:
        raise IntegrityError("Runtime manifest source differs from the verified input")
    for name in ("analysis_id", "run_id", "package_sha256"):
        if runtime[name] != analysis_input[name]:
            raise IntegrityError(f"Runtime manifest {name} differs from the verified input")

    git_commit = runtime["git_commit"]
    if git_commit is not None and (
        not isinstance(git_commit, str)
        or not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", git_commit)
    ):
        raise ResultContractError("runtime manifest.git_commit is invalid")
    clean = runtime["git_worktree_clean"]
    if not isinstance(clean, bool):
        raise ResultContractError("runtime manifest.git_worktree_clean must be boolean")
    status_count = _integer(
        runtime["git_status_entry_count"],
        "runtime manifest.git_status_entry_count",
        ResultContractError,
        minimum=0,
    )
    if clean != (status_count == 0):
        raise ResultContractError("runtime manifest Git cleanliness fields disagree")

    wolfram = _strict_fields(
        runtime["wolfram"],
        {
            "wolframscript_path",
            "kernel_path",
            "version",
            "version_number",
            "release_number",
            "system_id",
            "processor_type",
            "media_backend",
        },
        "runtime manifest.wolfram",
        ResultContractError,
    )
    for name in ("wolframscript_path", "kernel_path", "processor_type"):
        _string(wolfram[name], f"runtime manifest.wolfram.{name}", ResultContractError)
    _number(
        wolfram["version_number"],
        "runtime manifest.wolfram.version_number",
        ResultContractError,
        minimum=15.0,
    )
    _integer(
        wolfram["release_number"],
        "runtime manifest.wolfram.release_number",
        ResultContractError,
        minimum=0,
    )
    if wolfram["media_backend"] != "Wolfram Language Import":
        raise ResultContractError("runtime manifest.wolfram.media_backend is unsupported")
    if wolfram["version"] != processor["wolfram_version"]:
        raise IntegrityError(
            "Result Wolfram version differs from the independently probed runtime"
        )
    if wolfram["system_id"] != processor["system_id"]:
        raise IntegrityError(
            "Result Wolfram system ID differs from the independently probed runtime"
        )

    python = _strict_fields(
        runtime["python"],
        {"executable", "role"},
        "runtime manifest.python",
        ResultContractError,
    )
    _string(python["executable"], "runtime manifest.python.executable", ResultContractError)
    if python["role"] != "input and output contract boundary only":
        raise ResultContractError("runtime manifest.python.role is unsupported")
    runtime_parameters = _strict_fields(
        runtime["analysis_parameters"],
        {
            "silence_threshold_db",
            "frame_seconds",
            "hop_seconds",
            "random_seed",
            "transcript_mode",
        },
        "runtime manifest.analysis_parameters",
        ResultContractError,
    )
    if {
        name: runtime_parameters[name] for name in DEFAULT_PARAMETERS
    } != analysis_input["parameters"]:
        raise IntegrityError("Runtime manifest parameters differ from the verified input")
    if runtime_parameters["transcript_mode"] != analysis_input["transcript"]["mode"]:
        raise IntegrityError("Runtime manifest transcript mode differs from the verified input")
    for name in ("speech_model_cache_requested", "repeatability_requested"):
        if not isinstance(runtime[name], bool):
            raise ResultContractError(f"runtime manifest.{name} must be boolean")


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
        "color_analysis",
        "motion_analysis",
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


def _validate_distribution(value: object, path: str) -> dict:
    fields = {
        "count",
        "minimum",
        "q05",
        "q25",
        "median",
        "q75",
        "q95",
        "maximum",
        "mean",
        "standard_deviation",
    }
    distribution = _strict_fields(value, fields, path, ResultContractError)
    count = _integer(distribution["count"], f"{path}.count", ResultContractError, minimum=0)
    ordered_fields = ("minimum", "q05", "q25", "median", "q75", "q95", "maximum")
    ordered = [
        _number(distribution[name], f"{path}.{name}", ResultContractError, nullable=True)
        for name in ordered_fields
    ]
    mean = _number(distribution["mean"], f"{path}.mean", ResultContractError, nullable=True)
    deviation = _number(
        distribution["standard_deviation"],
        f"{path}.standard_deviation",
        ResultContractError,
        minimum=0.0,
        nullable=True,
    )
    if count == 0:
        if any(item is not None for item in (*ordered, mean, deviation)):
            raise ResultContractError(f"{path} with count zero must contain null summaries")
    else:
        if any(item is None for item in (*ordered, mean, deviation)):
            raise ResultContractError(f"{path} with observations must contain numeric summaries")
        if ordered != sorted(ordered):
            raise ResultContractError(f"{path} quantiles must be ordered")
        if not ordered[0] <= mean <= ordered[-1]:
            raise ResultContractError(f"{path}.mean must lie within its observed range")
    return distribution


def _validate_histogram(value: object, path: str) -> None:
    histogram = _strict_fields(
        value, {"bin_edges", "counts", "fractions"}, path, ResultContractError
    )
    edges = histogram["bin_edges"]
    counts = histogram["counts"]
    fractions = histogram["fractions"]
    if not all(isinstance(item, list) for item in (edges, counts, fractions)):
        raise ResultContractError(f"{path} arrays are required")
    if len(counts) != len(fractions) or (counts and len(edges) != len(counts) + 1):
        raise ResultContractError(f"{path} bin dimensions are inconsistent")
    for index, edge in enumerate(edges):
        _number(edge, f"{path}.bin_edges[{index}]", ResultContractError)
    for index, count in enumerate(counts):
        _integer(count, f"{path}.counts[{index}]", ResultContractError, minimum=0)
    for index, fraction in enumerate(fractions):
        _number(
            fraction,
            f"{path}.fractions[{index}]",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
        )
    if fractions and not math.isclose(sum(fractions), 1.0, rel_tol=1e-8, abs_tol=1e-8):
        raise ResultContractError(f"{path}.fractions must sum to one")


def _validate_feature_availability(value: object, path: str) -> None:
    availability = _strict_fields(
        value, {"status", "observation_count", "reason"}, path, ResultContractError
    )
    status = _string(availability["status"], f"{path}.status", ResultContractError)
    if status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ResultContractError(f"{path}.status is unsupported")
    count = _integer(
        availability["observation_count"],
        f"{path}.observation_count",
        ResultContractError,
        minimum=0,
    )
    reason = _string(
        availability["reason"], f"{path}.reason", ResultContractError, nonempty=False
    )
    if status == "AVAILABLE" and (count < 1 or reason):
        raise ResultContractError(f"{path} AVAILABLE status requires observations and no reason")
    if status == "UNAVAILABLE" and not reason:
        raise ResultContractError(f"{path} UNAVAILABLE status requires a reason")


def _validate_audio_analytics(value: object, audio_available: bool) -> None:
    path = "measurements.audio_analytics"
    analytics = _strict_fields(
        value,
        {"status", "reason", "method", "dynamics", "distribution", "frequency", "pitch", "availability"},
        path,
        ResultContractError,
    )
    status = _string(analytics["status"], f"{path}.status", ResultContractError)
    reason = _string(analytics["reason"], f"{path}.reason", ResultContractError, nonempty=False)
    _string(analytics["method"], f"{path}.method", ResultContractError)
    if audio_available and (status != "AVAILABLE" or reason):
        raise ResultContractError("Available audio requires AVAILABLE extended analytics")
    if not audio_available and (status != "UNAVAILABLE" or not reason):
        raise ResultContractError("Unavailable audio requires explicit unavailable analytics")

    dynamics = analytics["dynamics"]
    distributions = analytics["distribution"]
    frequency = analytics["frequency"]
    if audio_available:
        dynamics = _strict_fields(
            dynamics,
            {
                "rms_amplitude", "peak_amplitude", "rms_dbfs", "local_loudness",
                "crest_factor", "crest_factor_db", "local_dynamic_range_db",
            },
            f"{path}.dynamics",
            ResultContractError,
        )
        for name in ("rms_amplitude", "peak_amplitude", "rms_dbfs", "local_loudness"):
            _validate_distribution(dynamics[name], f"{path}.dynamics.{name}")
        _number(dynamics["crest_factor"], f"{path}.dynamics.crest_factor", ResultContractError, minimum=0.0, nullable=True)
        _number(dynamics["crest_factor_db"], f"{path}.dynamics.crest_factor_db", ResultContractError, nullable=True)
        _number(dynamics["local_dynamic_range_db"], f"{path}.dynamics.local_dynamic_range_db", ResultContractError, minimum=0.0, nullable=True)
        distributions = _strict_fields(
            distributions,
            {"rms_amplitude_histogram", "rms_dbfs_histogram"},
            f"{path}.distribution",
            ResultContractError,
        )
        _validate_histogram(distributions["rms_amplitude_histogram"], f"{path}.distribution.rms_amplitude_histogram")
        _validate_histogram(distributions["rms_dbfs_histogram"], f"{path}.distribution.rms_dbfs_histogram")
        frequency = _strict_fields(
            frequency,
            {"spectral_centroid_hz", "spectral_spread_hz", "zero_crossing_rate", "nyquist_frequency_hz"},
            f"{path}.frequency",
            ResultContractError,
        )
        for name in ("spectral_centroid_hz", "spectral_spread_hz", "zero_crossing_rate"):
            _validate_distribution(frequency[name], f"{path}.frequency.{name}")
        _number(frequency["nyquist_frequency_hz"], f"{path}.frequency.nyquist_frequency_hz", ResultContractError, minimum=0.0)
    else:
        for name, candidate in (("dynamics", dynamics), ("distribution", distributions), ("frequency", frequency)):
            if candidate != {}:
                raise ResultContractError(f"{path}.{name} must be empty without audio")

    pitch = _strict_fields(
        analytics["pitch"],
        {"status", "reason", "method", "observation_count", "window_count", "coverage_fraction", "fundamental_frequency_hz"},
        f"{path}.pitch",
        ResultContractError,
    )
    pitch_status = _string(
        pitch["status"], f"{path}.pitch.status", ResultContractError
    )
    if pitch_status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ResultContractError(f"{path}.pitch.status is unsupported")
    pitch_reason = _string(
        pitch["reason"],
        f"{path}.pitch.reason",
        ResultContractError,
        nonempty=False,
    )
    _string(pitch["method"], f"{path}.pitch.method", ResultContractError)
    pitch_count = _integer(pitch["observation_count"], f"{path}.pitch.observation_count", ResultContractError, minimum=0)
    window_count = _integer(pitch["window_count"], f"{path}.pitch.window_count", ResultContractError, minimum=0)
    coverage = _number(pitch["coverage_fraction"], f"{path}.pitch.coverage_fraction", ResultContractError, minimum=0.0, maximum=1.0)
    if pitch_count > window_count or (window_count and not math.isclose(coverage, pitch_count / window_count, rel_tol=1e-8, abs_tol=1e-8)):
        raise ResultContractError(f"{path}.pitch coverage is inconsistent")
    if not window_count and coverage != 0.0:
        raise ResultContractError(f"{path}.pitch coverage requires observed windows")
    if pitch_status == "AVAILABLE" and (pitch_count < 1 or pitch_reason):
        raise ResultContractError(
            f"{path}.pitch AVAILABLE status requires observations and no reason"
        )
    if pitch_status == "UNAVAILABLE" and (pitch_count != 0 or not pitch_reason):
        raise ResultContractError(
            f"{path}.pitch UNAVAILABLE status requires zero observations and a reason"
        )
    pitch_distribution = _validate_distribution(
        pitch["fundamental_frequency_hz"],
        f"{path}.pitch.fundamental_frequency_hz",
    )
    if pitch_distribution["count"] != pitch_count:
        raise ResultContractError(
            f"{path}.pitch distribution count differs from observation_count"
        )

    availability = _strict_fields(
        analytics["availability"],
        {"rms_amplitude", "peak_amplitude", "spectral_centroid", "spectral_spread", "zero_crossing_rate", "local_loudness", "fundamental_frequency"},
        f"{path}.availability",
        ResultContractError,
    )
    for name, record in availability.items():
        _validate_feature_availability(record, f"{path}.availability.{name}")
    pitch_availability = availability["fundamental_frequency"]
    if (
        pitch_availability["status"] != pitch_status
        or pitch_availability["observation_count"] != pitch_count
    ):
        raise ResultContractError(
            f"{path}.pitch differs from fundamental-frequency availability"
        )


def _validate_rgb(value: object, path: str) -> None:
    rgb = _strict_fields(value, {"red", "green", "blue"}, path, ResultContractError)
    for name in ("red", "green", "blue"):
        _number(rgb[name], f"{path}.{name}", ResultContractError, minimum=0.0, maximum=1.0)


def _validate_video_analytics(value: object, duration: float, frame_count: int) -> None:
    path = "measurements.video_analytics"
    analytics = _strict_fields(
        value, {"sample_times_seconds", "per_frame", "color", "scene_changes"}, path, ResultContractError
    )
    times = analytics["sample_times_seconds"]
    frames = analytics["per_frame"]
    if not isinstance(times, list) or not isinstance(frames, list) or len(times) != frame_count or len(frames) != frame_count:
        raise ResultContractError(f"{path} must contain one timestamped row per sampled frame")
    previous = -1.0
    for index, time_value in enumerate(times):
        time_value = _number(time_value, f"{path}.sample_times_seconds[{index}]", ResultContractError, minimum=0.0, maximum=duration)
        if time_value < previous:
            raise ResultContractError(f"{path}.sample_times_seconds must be ordered")
        previous = time_value
    frame_fields = {
        "sample_index", "time_seconds", "frame_difference", "color_histogram_distance",
        "brightness", "saturation", "contrast", "colorfulness", "mean_rgb", "mean_color_hex",
    }
    for index, raw_frame in enumerate(frames):
        frame = _strict_fields(raw_frame, frame_fields, f"{path}.per_frame[{index}]", ResultContractError)
        if _integer(frame["sample_index"], f"{path}.per_frame[{index}].sample_index", ResultContractError, minimum=1) != index + 1:
            raise ResultContractError(f"{path}.per_frame sample indexes must be consecutive")
        frame_time = _number(frame["time_seconds"], f"{path}.per_frame[{index}].time_seconds", ResultContractError, minimum=0.0, maximum=duration)
        if not math.isclose(frame_time, times[index], rel_tol=1e-9, abs_tol=1e-9):
            raise ResultContractError(f"{path}.per_frame time differs from sample_times_seconds")
        bounded_features = {
            "frame_difference": 1.0,
            "color_histogram_distance": 1.0,
            "brightness": 1.0,
            "saturation": 1.0,
            "contrast": 1.0,
            "colorfulness": 2.0,
        }
        for name, maximum in bounded_features.items():
            _number(
                frame[name],
                f"{path}.per_frame[{index}].{name}",
                ResultContractError,
                minimum=0.0,
                maximum=maximum,
            )
        _validate_rgb(frame["mean_rgb"], f"{path}.per_frame[{index}].mean_rgb")
        if not re.fullmatch(r"#[A-F0-9]{6}", _string(frame["mean_color_hex"], f"{path}.per_frame[{index}].mean_color_hex", ResultContractError)):
            raise ResultContractError(f"{path}.per_frame[{index}].mean_color_hex is invalid")

    color = _strict_fields(
        analytics["color"],
        {"method", "mean_rgb", "palette", "brightness", "saturation", "contrast", "colorfulness"},
        f"{path}.color",
        ResultContractError,
    )
    _string(color["method"], f"{path}.color.method", ResultContractError)
    _validate_rgb(color["mean_rgb"], f"{path}.color.mean_rgb")
    palette = color["palette"]
    if not isinstance(palette, list) or not 1 <= len(palette) <= 8:
        raise ResultContractError(f"{path}.color.palette must contain one to eight colors")
    palette_fraction = 0.0
    for index, raw_color in enumerate(palette):
        item = _strict_fields(raw_color, {"rank", "hex", "rgb", "fraction"}, f"{path}.color.palette[{index}]", ResultContractError)
        if _integer(item["rank"], f"{path}.color.palette[{index}].rank", ResultContractError, minimum=1) != index + 1:
            raise ResultContractError(f"{path}.color.palette ranks must be consecutive")
        if not re.fullmatch(
            r"#[A-F0-9]{6}",
            _string(
                item["hex"],
                f"{path}.color.palette[{index}].hex",
                ResultContractError,
            ),
        ):
            raise ResultContractError(
                f"{path}.color.palette[{index}].hex is invalid"
            )
        _validate_rgb(item["rgb"], f"{path}.color.palette[{index}].rgb")
        palette_fraction += _number(
            item["fraction"],
            f"{path}.color.palette[{index}].fraction",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
        )
    if palette_fraction <= 0.0 or palette_fraction > 1.0 + 1e-8:
        raise ResultContractError(
            f"{path}.color.palette fractions must describe a non-empty subset"
        )
    for name in ("brightness", "saturation", "contrast", "colorfulness"):
        distribution = _validate_distribution(color[name], f"{path}.color.{name}")
        if distribution["count"] != frame_count:
            raise ResultContractError(f"{path}.color.{name}.count differs from sampled frames")

    scene = _strict_fields(analytics["scene_changes"], {"method", "threshold", "candidates"}, f"{path}.scene_changes", ResultContractError)
    _string(scene["method"], f"{path}.scene_changes.method", ResultContractError)
    _number(scene["threshold"], f"{path}.scene_changes.threshold", ResultContractError, minimum=0.0, nullable=True)
    candidates = scene["candidates"]
    if not isinstance(candidates, list):
        raise ResultContractError(f"{path}.scene_changes.candidates must be an array")
    for index, raw_candidate in enumerate(candidates):
        candidate = _strict_fields(raw_candidate, {"from_sample_index", "to_sample_index", "time_seconds", "score", "frame_difference", "color_histogram_distance"}, f"{path}.scene_changes.candidates[{index}]", ResultContractError)
        start = _integer(candidate["from_sample_index"], f"{path}.scene_changes.candidates[{index}].from_sample_index", ResultContractError, minimum=1)
        finish = _integer(candidate["to_sample_index"], f"{path}.scene_changes.candidates[{index}].to_sample_index", ResultContractError, minimum=2)
        if finish != start + 1 or finish > frame_count:
            raise ResultContractError(f"{path}.scene_changes candidate indexes are inconsistent")
        _number(
            candidate["time_seconds"],
            f"{path}.scene_changes.candidates[{index}].time_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        for name in ("score", "frame_difference", "color_histogram_distance"):
            _number(
                candidate[name],
                f"{path}.scene_changes.candidates[{index}].{name}",
                ResultContractError,
                minimum=0.0,
            )


def _validate_whisper_model(value: object, path: str) -> dict:
    model = _strict_fields(
        value,
        {
            "status",
            "reason",
            "repository_resource_name",
            "resource_uuid",
            "resource_version",
            "size",
            "target_device",
            "network_mode",
            "artifacts",
            "identity_sha256",
        },
        path,
        ResultContractError,
    )
    status = _string(model["status"], f"{path}.status", ResultContractError)
    if status not in {"VERIFIED", "NOT_CACHED", "IDENTITY_MISMATCH"}:
        raise ResultContractError(f"{path}.status is unsupported")
    reason = _string(
        model["reason"], f"{path}.reason", ResultContractError, nonempty=False
    )
    for name in (
        "repository_resource_name",
        "resource_uuid",
        "resource_version",
        "size",
        "target_device",
        "network_mode",
    ):
        expected = WHISPER_MODEL_IDENTITY[name]
        if model[name] != expected:
            raise ResultContractError(f"{path}.{name} differs from the pinned model")
    if status == "VERIFIED" and reason:
        raise ResultContractError(f"{path}.reason must be empty when VERIFIED")
    if status != "VERIFIED" and not reason:
        raise ResultContractError(f"{path}.reason must explain an unverified model")

    artifacts = model["artifacts"]
    if not isinstance(artifacts, dict):
        raise ResultContractError(f"{path}.artifacts must be an object")
    if artifacts:
        artifacts = _strict_fields(
            artifacts, set(WHISPER_ARTIFACTS), f"{path}.artifacts", ResultContractError
        )
        for name, expected in WHISPER_ARTIFACTS.items():
            artifact_path = f"{path}.artifacts.{name}"
            artifact = _strict_fields(
                artifacts[name],
                {
                    "content_element",
                    "sha256",
                    "size_bytes",
                    "status",
                    "actual_sha256",
                    "actual_size_bytes",
                },
                artifact_path,
                ResultContractError,
            )
            for field in ("content_element", "sha256", "size_bytes"):
                if artifact[field] != expected[field]:
                    raise ResultContractError(
                        f"{artifact_path}.{field} differs from the pinned artifact"
                    )
            artifact_status = _string(
                artifact["status"], f"{artifact_path}.status", ResultContractError
            )
            if artifact_status not in {"VERIFIED", "NOT_CACHED", "HASH_MISMATCH"}:
                raise ResultContractError(f"{artifact_path}.status is unsupported")
            actual_sha = artifact["actual_sha256"]
            actual_size = artifact["actual_size_bytes"]
            if actual_sha is not None:
                _sha256(actual_sha, f"{artifact_path}.actual_sha256", ResultContractError)
            if actual_size is not None:
                _integer(
                    actual_size,
                    f"{artifact_path}.actual_size_bytes",
                    ResultContractError,
                    minimum=1,
                )
            if artifact_status == "VERIFIED" and (
                actual_sha != expected["sha256"]
                or actual_size != expected["size_bytes"]
            ):
                raise ResultContractError(
                    f"{artifact_path} claims VERIFIED with a different identity"
                )

    identity = model["identity_sha256"]
    if status == "VERIFIED":
        if set(artifacts) != set(WHISPER_ARTIFACTS):
            raise ResultContractError(
                f"{path}.artifacts must include every pinned model component"
            )
        if identity != WHISPER_MODEL_IDENTITY["identity_sha256"]:
            raise ResultContractError(f"{path}.identity_sha256 is not the pinned identity")
    elif identity is not None:
        raise ResultContractError(f"{path}.identity_sha256 must be null when unverified")
    return model


def _validate_whisper_inference(value: object, path: str) -> None:
    inference = _strict_fields(
        value,
        {
            "chunk_seconds",
            "chunk_count",
            "max_tokens_per_chunk",
            "sampling",
            "temperature",
            "target_device",
            "network_mode",
        },
        path,
        ResultContractError,
    )
    if _number(
        inference["chunk_seconds"],
        f"{path}.chunk_seconds",
        ResultContractError,
        minimum=0.000001,
    ) != 30.0:
        raise ResultContractError(f"{path}.chunk_seconds must match the pinned method")
    _integer(
        inference["chunk_count"],
        f"{path}.chunk_count",
        ResultContractError,
        minimum=1,
    )
    if _integer(
        inference["max_tokens_per_chunk"],
        f"{path}.max_tokens_per_chunk",
        ResultContractError,
        minimum=1,
    ) != 224:
        raise ResultContractError(
            f"{path}.max_tokens_per_chunk must match the pinned method"
        )
    if inference["sampling"] != "greedy_argmax" or inference["temperature"] != 0.0:
        raise ResultContractError(f"{path} must use deterministic greedy decoding")
    if inference["target_device"] != "CPU" or inference["network_mode"] != "disabled":
        raise ResultContractError(f"{path} must be local CPU inference with networking disabled")


def _validate_transcript_measurement(
    value: object,
    duration: float,
    capability: dict,
    transcript_config: dict,
) -> None:
    path = "measurements.transcript"
    transcript = _strict_fields(
        value,
        {"status", "reason", "method", "text", "segments", "statistics", "model", "sidecar", "inference"},
        path,
        ResultContractError,
    )
    status = _string(transcript["status"], f"{path}.status", ResultContractError)
    if status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ResultContractError(f"{path}.status is unsupported")
    reason = _string(transcript["reason"], f"{path}.reason", ResultContractError, nonempty=False)
    method = _string(transcript["method"], f"{path}.method", ResultContractError)
    if method not in {
        "wolfram_whisper_v1_tiny",
        "sidecar",
        "disabled",
        "configuration",
    }:
        raise ResultContractError(f"{path}.method is unsupported")
    text_value = _string(transcript["text"], f"{path}.text", ResultContractError, nonempty=False)
    segments = transcript["segments"]
    if not isinstance(segments, list):
        raise ResultContractError(f"{path}.segments must be an array")
    for index, raw_segment in enumerate(segments):
        segment = _strict_fields(raw_segment, {"start_seconds", "end_seconds", "text"}, f"{path}.segments[{index}]", ResultContractError)
        start = _number(segment["start_seconds"], f"{path}.segments[{index}].start_seconds", ResultContractError, minimum=0.0, maximum=duration)
        end = _number(segment["end_seconds"], f"{path}.segments[{index}].end_seconds", ResultContractError, minimum=0.0, maximum=duration)
        if end < start:
            raise ResultContractError(f"{path}.segments[{index}] ends before it starts")
        _string(segment["text"], f"{path}.segments[{index}].text", ResultContractError)
    statistics = _strict_fields(
        transcript["statistics"],
        {"character_count", "word_count", "sentence_count", "unique_word_count", "lexical_diversity", "words_per_minute", "top_terms"},
        f"{path}.statistics",
        ResultContractError,
    )
    for name in ("character_count", "word_count", "sentence_count", "unique_word_count"):
        _integer(statistics[name], f"{path}.statistics.{name}", ResultContractError, minimum=0)
    if statistics["character_count"] != len(text_value):
        raise ResultContractError(
            f"{path}.statistics.character_count differs from transcript text"
        )
    if statistics["unique_word_count"] > statistics["word_count"]:
        raise ResultContractError(
            f"{path}.statistics.unique_word_count exceeds word_count"
        )
    _number(statistics["lexical_diversity"], f"{path}.statistics.lexical_diversity", ResultContractError, minimum=0.0, maximum=1.0, nullable=True)
    _number(statistics["words_per_minute"], f"{path}.statistics.words_per_minute", ResultContractError, minimum=0.0, nullable=True)
    terms = statistics["top_terms"]
    if not isinstance(terms, list) or len(terms) > 15:
        raise ResultContractError(f"{path}.statistics.top_terms must be a bounded array")
    for index, raw_term in enumerate(terms):
        term = _strict_fields(raw_term, {"term", "count"}, f"{path}.statistics.top_terms[{index}]", ResultContractError)
        _string(term["term"], f"{path}.statistics.top_terms[{index}].term", ResultContractError)
        _integer(term["count"], f"{path}.statistics.top_terms[{index}].count", ResultContractError, minimum=1)
    capability_status = capability["status"]
    if status == "AVAILABLE":
        if capability_status != "USED" or reason or not text_value:
            raise ResultContractError("Available transcript requires USED capability and non-empty text")
        if method == "sidecar" and transcript["sidecar"] is None:
            raise ResultContractError("Sidecar transcript must include sidecar provenance")
        if method == "sidecar":
            configured_sidecar = transcript_config["sidecar"]
            if configured_sidecar is None:
                raise ResultContractError(
                    "Sidecar transcript requires a verified input sidecar"
                )
            sidecar = _strict_fields(
                transcript["sidecar"],
                {"format", "sha256", "size_bytes"},
                f"{path}.sidecar",
                ResultContractError,
            )
            if (
                sidecar["format"] != configured_sidecar["format"]
                or sidecar["sha256"] != configured_sidecar["sha256"]
                or sidecar["size_bytes"] != configured_sidecar["size_bytes"]
            ):
                raise IntegrityError(
                    "Transcript result sidecar identity differs from verified input"
                )
            if transcript["model"] is not None or transcript["inference"] is not None:
                raise ResultContractError(
                    "Sidecar transcript must not claim model inference provenance"
                )
        if method == "wolfram_whisper_v1_tiny" and (
            transcript["model"] is None or transcript["inference"] is None
        ):
            raise ResultContractError(
                "Whisper transcript must include model and inference provenance"
            )
        if method == "wolfram_whisper_v1_tiny":
            model = _validate_whisper_model(
                transcript["model"], f"{path}.model"
            )
            if model["status"] != "VERIFIED":
                raise ResultContractError(
                    "Available Whisper transcript requires a verified pinned model"
                )
            _validate_whisper_inference(
                transcript["inference"], f"{path}.inference"
            )
            if transcript["sidecar"] is not None:
                raise ResultContractError(
                    "Whisper transcript must not claim sidecar provenance"
                )
        if method not in {"sidecar", "wolfram_whisper_v1_tiny"}:
            raise ResultContractError(
                "Available transcript uses an unavailable-only method"
            )
    else:
        if capability_status == "USED" or not reason or text_value or segments:
            raise ResultContractError("Unavailable transcript must be empty and explained")
        if any(statistics[name] != 0 for name in (
            "character_count", "word_count", "sentence_count", "unique_word_count"
        )) or statistics["top_terms"]:
            raise ResultContractError(
                "Unavailable transcript statistics must be empty"
            )
        if transcript["model"] is not None:
            _validate_whisper_model(transcript["model"], f"{path}.model")
        if transcript["sidecar"] is not None or transcript["inference"] is not None:
            raise ResultContractError(
                "Unavailable transcript must not claim completed source or inference provenance"
            )


def _validate_audio_activity(
    value: object,
    duration: float,
    audio_available: bool,
    parameters: dict,
    audible_intervals: list,
) -> None:
    path = "measurements.audio_activity"
    activity = _strict_fields(
        value,
        {
            "status",
            "reason",
            "method",
            "threshold_dbfs",
            "merge_gap_seconds",
            "minimum_region_seconds",
            "audible_coverage_fraction",
            "regions",
        },
        path,
        ResultContractError,
    )
    status = _string(activity["status"], f"{path}.status", ResultContractError)
    reason = _string(
        activity["reason"], f"{path}.reason", ResultContractError, nonempty=False
    )
    _string(activity["method"], f"{path}.method", ResultContractError)
    threshold = _number(
        activity["threshold_dbfs"], f"{path}.threshold_dbfs", ResultContractError
    )
    if not math.isclose(
        threshold,
        parameters["silence_threshold_db"],
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ResultContractError(f"{path}.threshold_dbfs differs from analysis parameters")
    merge_gap = _number(
        activity["merge_gap_seconds"],
        f"{path}.merge_gap_seconds",
        ResultContractError,
        minimum=0.0,
    )
    minimum_region = _number(
        activity["minimum_region_seconds"],
        f"{path}.minimum_region_seconds",
        ResultContractError,
        minimum=0.0,
    )
    coverage = _number(
        activity["audible_coverage_fraction"],
        f"{path}.audible_coverage_fraction",
        ResultContractError,
        minimum=0.0,
        maximum=1.0,
        nullable=not audio_available,
    )
    regions = activity["regions"]
    if not isinstance(regions, list):
        raise ResultContractError(f"{path}.regions must be an array")
    if audio_available:
        if status != "AVAILABLE" or reason:
            raise ResultContractError(f"{path} must be AVAILABLE without a reason")
        expected_coverage = sum(end - start for start, end in audible_intervals) / duration
        if not math.isclose(
            coverage, expected_coverage, rel_tol=1e-8, abs_tol=1e-8
        ):
            raise ResultContractError(
                f"{path}.audible_coverage_fraction differs from audible intervals"
            )
    elif status != "UNAVAILABLE" or not reason or coverage is not None or regions:
        raise ResultContractError(
            f"{path} must be empty and explained when audio is unavailable"
        )

    previous_end = -1.0
    for index, raw_region in enumerate(regions):
        region_path = f"{path}.regions[{index}]"
        region = _strict_fields(
            raw_region,
            {
                "region_index",
                "start_seconds",
                "end_seconds",
                "active_duration_seconds",
                "interval_count",
                "duration_seconds",
                "activity_fraction",
            },
            region_path,
            ResultContractError,
        )
        if _integer(
            region["region_index"],
            f"{region_path}.region_index",
            ResultContractError,
            minimum=1,
        ) != index + 1:
            raise ResultContractError(f"{path}.region indexes must be consecutive")
        start = _number(
            region["start_seconds"],
            f"{region_path}.start_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        end = _number(
            region["end_seconds"],
            f"{region_path}.end_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        region_duration = _number(
            region["duration_seconds"],
            f"{region_path}.duration_seconds",
            ResultContractError,
            minimum=0.0,
        )
        active_duration = _number(
            region["active_duration_seconds"],
            f"{region_path}.active_duration_seconds",
            ResultContractError,
            minimum=0.0,
        )
        fraction = _number(
            region["activity_fraction"],
            f"{region_path}.activity_fraction",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
        )
        _integer(
            region["interval_count"],
            f"{region_path}.interval_count",
            ResultContractError,
            minimum=1,
        )
        if end <= start or end - start + 1e-9 < minimum_region:
            raise ResultContractError(f"{region_path} has an invalid duration")
        if start < previous_end - 1e-9:
            raise ResultContractError(f"{path}.regions must be ordered and non-overlapping")
        if not math.isclose(region_duration, end - start, rel_tol=1e-8, abs_tol=1e-8):
            raise ResultContractError(f"{region_path}.duration_seconds is inconsistent")
        if active_duration > region_duration + 1e-8 or not math.isclose(
            fraction,
            active_duration / region_duration,
            rel_tol=1e-8,
            abs_tol=1e-8,
        ):
            raise ResultContractError(f"{region_path}.activity_fraction is inconsistent")
        previous_end = end


def _validate_speech_segments(
    value: object, duration: float, transcript: dict
) -> None:
    path = "measurements.speech_segments"
    speech = _strict_fields(
        value,
        {
            "status",
            "reason",
            "method",
            "timing_basis",
            "speaker_diarization",
            "segment_count",
            "segments",
        },
        path,
        ResultContractError,
    )
    status = _string(speech["status"], f"{path}.status", ResultContractError)
    reason = _string(
        speech["reason"], f"{path}.reason", ResultContractError, nonempty=False
    )
    _string(speech["method"], f"{path}.method", ResultContractError)
    timing_basis = _string(
        speech["timing_basis"], f"{path}.timing_basis", ResultContractError
    )
    if timing_basis not in {
        "UNAVAILABLE",
        "SOURCE_SEGMENTS",
        "MIXED_WITH_ESTIMATED_SENTENCE_TIMING",
    }:
        raise ResultContractError(f"{path}.timing_basis is unsupported")
    if speech["speaker_diarization"] != "NOT_PERFORMED":
        raise ResultContractError(
            f"{path}.speaker_diarization must disclose that diarization was not performed"
        )
    count = _integer(
        speech["segment_count"],
        f"{path}.segment_count",
        ResultContractError,
        minimum=0,
    )
    segments = speech["segments"]
    if not isinstance(segments, list) or len(segments) != count:
        raise ResultContractError(f"{path}.segments differs from segment_count")
    transcript_available = transcript["status"] == "AVAILABLE"
    if transcript_available:
        if status != "AVAILABLE" or reason or count < 1 or timing_basis == "UNAVAILABLE":
            raise ResultContractError(
                f"{path} must contain navigable segments for an available transcript"
            )
    elif status != "UNAVAILABLE" or not reason or count or segments or timing_basis != "UNAVAILABLE":
        raise ResultContractError(
            f"{path} must be empty and explained when the transcript is unavailable"
        )

    previous_start = -1.0
    for index, raw_segment in enumerate(segments):
        segment_path = f"{path}.segments[{index}]"
        segment = _strict_fields(
            raw_segment,
            {
                "segment_index",
                "source_segment_index",
                "sentence_index",
                "start_seconds",
                "end_seconds",
                "duration_seconds",
                "text",
                "word_count",
                "timing_basis",
            },
            segment_path,
            ResultContractError,
        )
        if _integer(
            segment["segment_index"],
            f"{segment_path}.segment_index",
            ResultContractError,
            minimum=1,
        ) != index + 1:
            raise ResultContractError(f"{path}.segment indexes must be consecutive")
        for name in ("source_segment_index", "sentence_index", "word_count"):
            _integer(
                segment[name],
                f"{segment_path}.{name}",
                ResultContractError,
                minimum=1,
            )
        start = _number(
            segment["start_seconds"],
            f"{segment_path}.start_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        end = _number(
            segment["end_seconds"],
            f"{segment_path}.end_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        segment_duration = _number(
            segment["duration_seconds"],
            f"{segment_path}.duration_seconds",
            ResultContractError,
            minimum=0.0,
        )
        _string(segment["text"], f"{segment_path}.text", ResultContractError)
        if segment["timing_basis"] not in {
            "SOURCE_SEGMENT",
            "PROPORTIONAL_WITHIN_SOURCE_SEGMENT",
        }:
            raise ResultContractError(f"{segment_path}.timing_basis is unsupported")
        if end < start or start < previous_start:
            raise ResultContractError(f"{path}.segments must be ordered with valid bounds")
        if not math.isclose(
            segment_duration, end - start, rel_tol=1e-8, abs_tol=1e-8
        ):
            raise ResultContractError(f"{segment_path}.duration_seconds is inconsistent")
        previous_start = start


def _validate_scene_segments(value: object, duration: float) -> None:
    path = "measurements.scene_segments"
    scenes = _strict_fields(
        value,
        {
            "status",
            "reason",
            "method",
            "minimum_separation_seconds",
            "boundary_count",
            "segments",
        },
        path,
        ResultContractError,
    )
    if scenes["status"] != "AVAILABLE" or scenes["reason"] != "":
        raise ResultContractError(f"{path} must be available for a validated video")
    _string(scenes["method"], f"{path}.method", ResultContractError)
    _number(
        scenes["minimum_separation_seconds"],
        f"{path}.minimum_separation_seconds",
        ResultContractError,
        minimum=0.0,
    )
    boundary_count = _integer(
        scenes["boundary_count"],
        f"{path}.boundary_count",
        ResultContractError,
        minimum=0,
    )
    segments = scenes["segments"]
    if not isinstance(segments, list) or len(segments) != boundary_count + 1:
        raise ResultContractError(
            f"{path}.segments must contain one more scene than boundaries"
        )
    previous_end = 0.0
    for index, raw_segment in enumerate(segments):
        segment_path = f"{path}.segments[{index}]"
        segment = _strict_fields(
            raw_segment,
            {
                "scene_index",
                "start_seconds",
                "end_seconds",
                "duration_seconds",
                "sample_count",
                "representative_time_seconds",
                "mean_brightness",
                "mean_motion",
                "mean_colorfulness",
                "representative_color_hex",
                "entry_boundary_score",
            },
            segment_path,
            ResultContractError,
        )
        if _integer(
            segment["scene_index"],
            f"{segment_path}.scene_index",
            ResultContractError,
            minimum=1,
        ) != index + 1:
            raise ResultContractError(f"{path}.scene indexes must be consecutive")
        start = _number(
            segment["start_seconds"],
            f"{segment_path}.start_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        end = _number(
            segment["end_seconds"],
            f"{segment_path}.end_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        segment_duration = _number(
            segment["duration_seconds"],
            f"{segment_path}.duration_seconds",
            ResultContractError,
            minimum=0.0,
        )
        if end <= start or not math.isclose(start, previous_end, abs_tol=1e-8):
            raise ResultContractError(f"{path}.segments must be positive and contiguous")
        if not math.isclose(segment_duration, end - start, rel_tol=1e-8, abs_tol=1e-8):
            raise ResultContractError(f"{segment_path}.duration_seconds is inconsistent")
        _integer(
            segment["sample_count"],
            f"{segment_path}.sample_count",
            ResultContractError,
            minimum=1,
        )
        representative = _number(
            segment["representative_time_seconds"],
            f"{segment_path}.representative_time_seconds",
            ResultContractError,
            minimum=start,
            maximum=end,
        )
        if representative < start or representative > end:
            raise ResultContractError(f"{segment_path} representative lies outside the scene")
        for name, maximum in (
            ("mean_brightness", 1.0),
            ("mean_motion", 1.0),
            ("mean_colorfulness", 2.0),
        ):
            _number(
                segment[name],
                f"{segment_path}.{name}",
                ResultContractError,
                minimum=0.0,
                maximum=maximum,
            )
        if not re.fullmatch(
            r"#[A-F0-9]{6}",
            _string(
                segment["representative_color_hex"],
                f"{segment_path}.representative_color_hex",
                ResultContractError,
            ),
        ):
            raise ResultContractError(f"{segment_path}.representative_color_hex is invalid")
        boundary_score = _number(
            segment["entry_boundary_score"],
            f"{segment_path}.entry_boundary_score",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
            nullable=index == 0,
        )
        if index == 0 and boundary_score is not None:
            raise ResultContractError(f"{segment_path}.entry_boundary_score must be null")
        if index > 0 and boundary_score is None:
            raise ResultContractError(f"{segment_path}.entry_boundary_score is required")
        previous_end = end
    if not math.isclose(previous_end, duration, rel_tol=1e-8, abs_tol=1e-8):
        raise ResultContractError(f"{path}.segments must cover the complete media duration")


def _validate_cross_modal(
    value: object, duration: float, audio_available: bool, capability: dict
) -> None:
    path = "measurements.cross_modal"
    cross_modal = _strict_fields(
        value,
        {
            "status",
            "reason",
            "method",
            "sample_count",
            "motion_rms_pearson_correlation",
            "aligned_samples",
            "events",
        },
        path,
        ResultContractError,
    )
    status = _string(cross_modal["status"], f"{path}.status", ResultContractError)
    reason = _string(
        cross_modal["reason"], f"{path}.reason", ResultContractError, nonempty=False
    )
    _string(cross_modal["method"], f"{path}.method", ResultContractError)
    count = _integer(
        cross_modal["sample_count"],
        f"{path}.sample_count",
        ResultContractError,
        minimum=0,
    )
    correlation = _number(
        cross_modal["motion_rms_pearson_correlation"],
        f"{path}.motion_rms_pearson_correlation",
        ResultContractError,
        minimum=-1.0,
        maximum=1.0,
        nullable=True,
    )
    samples = cross_modal["aligned_samples"]
    events = cross_modal["events"]
    if not isinstance(samples, list) or len(samples) != count:
        raise ResultContractError(f"{path}.aligned_samples differs from sample_count")
    if not isinstance(events, list):
        raise ResultContractError(f"{path}.events must be an array")
    if audio_available:
        if (
            status != "AVAILABLE"
            or reason
            or count < 1
            or capability["status"] != "USED"
        ):
            raise ResultContractError(
                f"{path} must be available when audio and video measurements exist"
            )
    elif (
        status != "UNAVAILABLE"
        or not reason
        or count
        or samples
        or events
        or correlation is not None
        or capability["status"] != "UNAVAILABLE"
    ):
        raise ResultContractError(
            f"{path} must be empty and explained when audio is unavailable"
        )

    previous_time = -1.0
    sample_fields = {
        "time_seconds",
        "motion",
        "rms_amplitude",
        "motion_normalized",
        "rms_normalized",
    }
    for index, raw_sample in enumerate(samples):
        sample_path = f"{path}.aligned_samples[{index}]"
        sample = _strict_fields(raw_sample, sample_fields, sample_path, ResultContractError)
        time_value = _number(
            sample["time_seconds"],
            f"{sample_path}.time_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        if time_value < previous_time:
            raise ResultContractError(f"{path}.aligned_samples must be time ordered")
        for name in ("motion", "rms_amplitude"):
            _number(
                sample[name], f"{sample_path}.{name}", ResultContractError, minimum=0.0
            )
        for name in ("motion_normalized", "rms_normalized"):
            _number(
                sample[name],
                f"{sample_path}.{name}",
                ResultContractError,
                minimum=0.0,
                maximum=1.0,
            )
        previous_time = time_value

    previous_event_time = -1.0
    event_fields = {
        "event_index",
        "event_type",
        "time_seconds",
        "window_seconds",
        "score",
        "scene_score",
        "motion",
        "rms_amplitude",
        "motion_normalized",
        "rms_normalized",
        "audio_activity",
        "transcript_text",
        "evidence_paths",
    }
    for index, raw_event in enumerate(events):
        event_path = f"{path}.events[{index}]"
        event = _strict_fields(raw_event, event_fields, event_path, ResultContractError)
        if _integer(
            event["event_index"],
            f"{event_path}.event_index",
            ResultContractError,
            minimum=1,
        ) != index + 1:
            raise ResultContractError(f"{path}.event indexes must be consecutive")
        event_type = _string(
            event["event_type"], f"{event_path}.event_type", ResultContractError
        )
        if event_type not in {
            "AUDIO_VISUAL_PEAK",
            "SCENE_CHANGE_WITH_AUDIO",
            "SCENE_CHANGE_IN_SILENCE",
        }:
            raise ResultContractError(f"{event_path}.event_type is unsupported")
        event_time = _number(
            event["time_seconds"],
            f"{event_path}.time_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        if event_time < previous_event_time:
            raise ResultContractError(f"{path}.events must be time ordered")
        window = event["window_seconds"]
        if not isinstance(window, list) or len(window) != 2:
            raise ResultContractError(f"{event_path}.window_seconds must be [start, end]")
        window_start = _number(
            window[0],
            f"{event_path}.window_seconds[0]",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        window_end = _number(
            window[1],
            f"{event_path}.window_seconds[1]",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
        )
        if window_start > event_time or event_time > window_end:
            raise ResultContractError(f"{event_path}.window_seconds must contain the event")
        _number(
            event["score"],
            f"{event_path}.score",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
        )
        _number(
            event["scene_score"],
            f"{event_path}.scene_score",
            ResultContractError,
            minimum=0.0,
            maximum=1.0,
            nullable=True,
        )
        for name in ("motion", "rms_amplitude"):
            _number(event[name], f"{event_path}.{name}", ResultContractError, minimum=0.0)
        for name in ("motion_normalized", "rms_normalized"):
            _number(
                event[name],
                f"{event_path}.{name}",
                ResultContractError,
                minimum=0.0,
                maximum=1.0,
            )
        if not isinstance(event["audio_activity"], bool):
            raise ResultContractError(f"{event_path}.audio_activity must be boolean")
        if event["transcript_text"] is not None:
            _string(
                event["transcript_text"],
                f"{event_path}.transcript_text",
                ResultContractError,
            )
        evidence_paths = _validate_string_array(
            event["evidence_paths"],
            f"{event_path}.evidence_paths",
            minimum=1,
        )
        if not all(item.startswith("measurements.") for item in evidence_paths):
            raise ResultContractError(f"{event_path}.evidence_paths must target measurements")
        previous_event_time = event_time


def _validate_insights(value: object, duration: float) -> None:
    path = "measurements.insights"
    insights = _strict_fields(value, {"method", "items"}, path, ResultContractError)
    _string(insights["method"], f"{path}.method", ResultContractError)
    items = insights["items"]
    if not isinstance(items, list):
        raise ResultContractError(f"{path}.items must be an array")
    for index, raw_item in enumerate(items):
        item_path = f"{path}.items[{index}]"
        item = _strict_fields(
            raw_item,
            {
                "insight_id",
                "kind",
                "headline",
                "statement",
                "time_seconds",
                "evidence_paths",
            },
            item_path,
            ResultContractError,
        )
        expected_id = f"insight-{index + 1:02d}"
        if item["insight_id"] != expected_id:
            raise ResultContractError(f"{path}.insight IDs must be consecutive")
        if item["kind"] not in {"OBSERVATION", "LIMITATION"}:
            raise ResultContractError(f"{item_path}.kind is unsupported")
        _string(item["headline"], f"{item_path}.headline", ResultContractError)
        _string(item["statement"], f"{item_path}.statement", ResultContractError)
        _number(
            item["time_seconds"],
            f"{item_path}.time_seconds",
            ResultContractError,
            minimum=0.0,
            maximum=duration,
            nullable=True,
        )
        evidence_paths = _validate_string_array(
            item["evidence_paths"],
            f"{item_path}.evidence_paths",
            minimum=1,
        )
        if not all(item.startswith("measurements.") for item in evidence_paths):
            raise ResultContractError(f"{item_path}.evidence_paths must target measurements")


def _validate_measurements(value: object, capabilities: dict, analysis_input: dict) -> None:
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
            "video_analytics",
            "audio_analytics",
            "transcript",
            "audio_activity",
            "speech_segments",
            "scene_segments",
            "cross_modal",
            "insights",
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
    for audible_index, audible in enumerate(
        measurements["audible_intervals_seconds"]
    ):
        for silence_index, silence in enumerate(
            measurements["silence_intervals_seconds"]
        ):
            if audible[0] < silence[1] and silence[0] < audible[1]:
                raise ResultContractError(
                    "measurements audible and silence intervals overlap at "
                    f"audible[{audible_index}] and silence[{silence_index}]"
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
    expected_event_types = {"SOURCE_DISCOVERED", "SOURCE_HASH_VERIFIED"}
    if analysis_input["transcript"]["sidecar"] is not None:
        expected_event_types.update(
            {"TRANSCRIPT_SOURCE_DISCOVERED", "TRANSCRIPT_SOURCE_HASH_VERIFIED"}
        )
    if set(event_types) != expected_event_types:
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
    _validate_video_analytics(
        measurements["video_analytics"],
        duration,
        measurements["video"]["frame_count_sampled"],
    )
    _validate_audio_analytics(measurements["audio_analytics"], audio_available)
    _validate_transcript_measurement(
        measurements["transcript"],
        duration,
        capabilities["transcript_analysis"],
        analysis_input["transcript"],
    )
    _validate_audio_activity(
        measurements["audio_activity"],
        audio_duration if audio_duration is not None else duration,
        audio_available,
        analysis_input["parameters"],
        measurements["audible_intervals_seconds"],
    )
    _validate_speech_segments(
        measurements["speech_segments"], duration, measurements["transcript"]
    )
    _validate_scene_segments(measurements["scene_segments"], duration)
    _validate_cross_modal(
        measurements["cross_modal"],
        duration,
        audio_available,
        capabilities["cross_modal_analysis"],
    )
    _validate_insights(measurements["insights"], duration)


def _validate_output_format(path: Path, name: str) -> None:
    prefix = path.read_bytes()[:4096]
    if name.endswith(".png"):
        if len(prefix) < 24 or prefix[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
            raise ResultContractError(f"output/{name} is not a PNG image")
        width, height = struct.unpack(">II", prefix[16:24])
        if width < 1 or height < 1:
            raise ResultContractError(f"output/{name} has invalid PNG dimensions")
        return
    try:
        text_prefix = prefix.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResultContractError(f"output/{name} is not valid UTF-8 text") from exc
    normalized = text_prefix.lstrip().casefold()
    if name == "analysis-notebook.nb" and not text_prefix.lstrip().startswith("Notebook["):
        raise ResultContractError("output/analysis-notebook.nb is not a Wolfram notebook expression")
    if name.endswith(".svg") and not (
        "<svg" in normalized and ("<?xml" in normalized or normalized.startswith("<svg"))
    ):
        raise ResultContractError(f"output/{name} is not an SVG document")
    if name.endswith(".html") and not (
        "<html" in normalized and ("<!doctype html" in normalized or "<head" in normalized)
    ):
        raise ResultContractError(f"output/{name} is not an HTML document")
    if name.endswith(".md") and not text_prefix.lstrip().startswith("#"):
        raise ResultContractError(f"output/{name} is not a Markdown report")


def _invalidate_result_markers(root: Path) -> None:
    for relative in ("output/result.json", "artefacts/repeatability.json"):
        candidate = root / relative
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.is_dir() and not candidate.is_symlink():
            raise ResultContractError(f"{relative} must not be a directory")
        candidate.unlink()


def _validate_outputs(
    root: Path,
    value: object,
    transcript: object,
    capabilities: dict,
) -> None:
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
        _validate_output_format(output_path, path)
    if seen != set(EXPECTED_OUTPUT_MEDIA_TYPES):
        raise ResultContractError("outputs do not contain the exact required artifact set")

    notebook_path = root / "output" / "analysis-notebook.nb"
    notebook_bytes = notebook_path.read_bytes()
    required_notebook_sections = (
        b"Executive overview",
        b"Video storyboard",
        b"Color analysis",
        b"Motion and temporal structure",
        b"Sound intelligence",
        b"Transcript and speech text",
        b"Cross-modal timeline",
        b"Provenance and evidence",
        b"Output inventory",
        b"Capabilities and methodology",
        b"Re-run through the verified package",
    )
    missing_sections = [
        section.decode("ascii")
        for section in required_notebook_sections
        if section not in notebook_bytes
    ]
    if missing_sections:
        raise ResultContractError(
            "analysis-notebook.nb is missing required analytical sections: "
            + ", ".join(missing_sections)
        )
    if notebook_bytes.count(b"GraphicsBox[") < 5:
        raise ResultContractError(
            "analysis-notebook.nb must embed at least five analytical graphics"
        )
    audio_interactive = capabilities["audio_track"]["status"] == "USED"
    transcript_interactive = isinstance(transcript, dict) and transcript.get("status") == "AVAILABLE"
    required_dynamic_modules = 3 + int(audio_interactive) + int(transcript_interactive)
    required_sliders = 2 + int(audio_interactive)
    if (
        notebook_bytes.count(b"DynamicModuleBox[") < required_dynamic_modules
        or notebook_bytes.count(b"SliderBox[") < required_sliders
    ):
        raise ResultContractError(
            "analysis-notebook.nb must contain native interactive Mathematica controls"
        )
    if b"AnimatorBox[" not in notebook_bytes:
        raise ResultContractError(
            "analysis-notebook.nb must contain sampled-frame navigation controls"
        )
    if b"ButtonBox[" not in notebook_bytes or b"Load local video" not in notebook_bytes:
        raise ResultContractError(
            "analysis-notebook.nb must contain an explicit local-video playback control"
        )
    if (audio_interactive or transcript_interactive) and b"PopupMenuBox[" not in notebook_bytes:
        raise ResultContractError(
            "analysis-notebook.nb must contain an available-data selector"
        )
    if transcript_interactive and b"InputFieldBox[" not in notebook_bytes:
        raise ResultContractError(
            "analysis-notebook.nb must contain transcript-search controls when a transcript is available"
        )
    if re.search(rb"InitializationCell\s*->\s*True", notebook_bytes) is None:
        raise ResultContractError(
            "analysis-notebook.nb must contain an executable initialization cell"
        )
    if re.search(rb'StyleDefinitions\s*->\s*"Default\.nb"', notebook_bytes) is None:
        raise ResultContractError(
            "analysis-notebook.nb must use Mathematica's default notebook styles"
        )
    if not isinstance(transcript, dict):
        raise ResultContractError("measurements.transcript must be an object")
    for field in ("status", "method"):
        expected = transcript.get(field)
        if not isinstance(expected, str) or expected.encode("utf-8") not in notebook_bytes:
            raise ResultContractError(
                f"analysis-notebook.nb is missing the actual transcript {field}"
            )


def validate_result(
    workspace: str | Path,
    *,
    raw_result_path: Path | None = None,
    input_path: Path | None = None,
) -> dict:
    """Validate Mathematica's raw result and atomically publish canonical JSON."""
    root = _workspace_path(workspace)
    _invalidate_result_markers(root)
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
            "transcript",
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
    for field in (
        "schema_version",
        "analysis_id",
        "object_id",
        "run_id",
        "source",
        "transcript",
        "evidence",
        "parameters",
    ):
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
    _validate_runtime_manifest(root, processor, analysis_input)

    _validate_capabilities(result["capabilities"])
    _validate_measurements(result["measurements"], result["capabilities"], analysis_input)
    provenance = _strict_fields(
        result["provenance_summary"],
        {"task_count", "artifact_count", "integrity_conflict_count", "evidence_sha256"},
        "provenance_summary",
        ResultContractError,
    )
    expected_task_count = 4 if analysis_input["transcript"]["sidecar"] is not None else 2
    expected_artifact_count = 2 if analysis_input["transcript"]["sidecar"] is not None else 1
    if (
        provenance["task_count"] != expected_task_count
        or provenance["artifact_count"] != expected_artifact_count
    ):
        raise ResultContractError("Provenance counts differ from the local source evidence")
    if provenance["integrity_conflict_count"] != 0:
        raise IntegrityError("Mathematica reported a provenance integrity conflict")
    if provenance["evidence_sha256"] != analysis_input["evidence"]["sha256"]:
        raise IntegrityError("Provenance evidence SHA-256 differs from verified input")
    _validate_outputs(
        root,
        result["outputs"],
        result["measurements"]["transcript"],
        result["capabilities"],
    )

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
    prepare.add_argument(
        "--transcript-mode",
        choices=sorted(TRANSCRIPT_MODES),
        default="prefer_sidecar",
    )

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
                transcript_mode=args.transcript_mode,
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
