#!/usr/bin/env python3
"""
Validate Airflow DAGs by compiling and loading with Airflow DagBag
This catches both Python syntax errors and import/parse errors that prevent
Airflow from displaying DAGs in the UI.
"""
import sys
import py_compile
from pathlib import Path


def compile_only(folder: Path) -> list[tuple[str, str]]:
    """Return a list of (filename, error) for syntax errors only."""
    errors: list[tuple[str, str]] = []
    dag_files = sorted(folder.glob("*.py"))
    print(f"Compiling {len(dag_files)} DAG file(s) for syntax...")
    for dag_file in dag_files:
        try:
            py_compile.compile(str(dag_file), doraise=True)
            print(f"  ✓ {dag_file.name}")
        except py_compile.PyCompileError as e:
            print(f"  ✗ {dag_file.name}: {e}")
            errors.append((dag_file.name, str(e)))
    return errors


def airflow_parse(folder: Path) -> tuple[int, dict[str, str]]:
    """Use Airflow DagBag to parse DAGs; returns (dag_count, import_errors)."""
    try:
        from airflow.models.dagbag import DagBag
    except Exception as e:  # pragma: no cover - defensive
        print(f"✗ Airflow not available in validation image: {e}")
        return (0, {"airflow": str(e)})

    bag = DagBag(dag_folder=str(folder), include_examples=False, safe_mode=False)
    dag_count = len(bag.dags)
    import_errors = {k: str(v) for k, v in bag.import_errors.items()}

    print(f"Parsed DAGs: {dag_count}")
    if import_errors:
        print("✗ Import errors detected by Airflow DagBag:")
        for file, err in import_errors.items():
            print(f"  {file}: {err}")
    else:
        print("✓ No import errors reported by Airflow DagBag")

    return dag_count, import_errors


def main():
    dag_folder = Path("/workspace/pipelines/airflow/dags")

    if not dag_folder.exists():
        print(f"✗ Error: DAG folder not found: {dag_folder}")
        sys.exit(1)

    # Step 1: Syntax compilation
    syntax_errors = compile_only(dag_folder)
    if syntax_errors:
        print("\n✗ Syntax errors detected:")
        for filename, error in syntax_errors:
            print(f"  {filename}: {error}")
        sys.exit(1)

    # Step 2: Airflow import/parse
    dag_count, import_errors = airflow_parse(dag_folder)
    if import_errors:
        print("\n✗ Validation failed due to import errors.")
        sys.exit(1)

    if dag_count == 0:
        print("\n✗ No DAGs discovered by Airflow.")
        sys.exit(1)

    print("\n✓ All DAGs validated successfully")


if __name__ == "__main__":
    main()
