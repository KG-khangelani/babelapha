#!/bin/bash
set -euo pipefail

echo "==> Installing Airflow for DAG validation"
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install "apache-airflow==2.9.1" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.1/constraints-3.11.txt"

# Install providers used in DAGs
pip install \
  apache-airflow-providers-cncf-kubernetes \
  apache-airflow-providers-amazon

echo "==> Validating DAG syntax"
python - <<'PYEOF'
import sys
import py_compile
from pathlib import Path

dag_folder = Path("pipelines/airflow/dags")
dag_files = list(dag_folder.glob("*.py"))

if not dag_files:
    print("✗ No DAG files found")
    sys.exit(1)

print(f"Found {len(dag_files)} DAG file(s)")
errors = []

for dag_file in dag_files:
    try:
        py_compile.compile(str(dag_file), doraise=True)
        print(f"  ✓ {dag_file.name}")
    except py_compile.PyCompileError as e:
        print(f"  ✗ {dag_file.name}: {e}")
        errors.append((dag_file.name, str(e)))

if errors:
    print("\n✗ Syntax errors detected:")
    for filename, error in errors:
        print(f"  {filename}: {error}")
    sys.exit(1)

print("\n✓ All DAG files passed syntax validation")
PYEOF
