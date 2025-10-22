#!/usr/bin/env python3
"""
Validate Airflow DAG syntax
"""
import sys
import py_compile
from pathlib import Path

def main():
    dag_folder = Path("/workspace/pipelines/airflow/dags")
    
    if not dag_folder.exists():
        print(f"✗ Error: DAG folder not found: {dag_folder}")
        sys.exit(1)
    
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

if __name__ == "__main__":
    main()
