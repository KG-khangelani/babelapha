#!/usr/bin/env python3
"""Create a verified Git-to-DAG-bundle identity sidecar."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


MODULE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_DIR / "dags"))

from provenance import build_code_identity, canonical_json_bytes, repository_git_commit


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bind a clean Git commit to every Python file in an Airflow DAG directory."
    )
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_dir = args.source_dir.resolve()
    requested_commit = args.git_commit.strip().lower()
    repository_commit = repository_git_commit(source_dir)
    if repository_commit is None:
        raise SystemExit(
            f"Refusing to attest a dirty or unversioned DAG bundle: {source_dir}"
        )
    if repository_commit != requested_commit:
        raise SystemExit(
            "Requested Git commit does not match the clean checkout: "
            f"requested={requested_commit} checkout={repository_commit}"
        )

    identity = build_code_identity(repository_commit, source_dir)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(canonical_json_bytes(identity))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "git_commit": identity["git_commit"],
                "bundle_sha256": identity["bundle_sha256"],
                "file_count": len(identity["files"]),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
