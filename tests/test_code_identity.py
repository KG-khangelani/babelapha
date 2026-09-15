import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "pipelines" / "airflow" / "create_code_identity.py"


class CodeIdentityGeneratorTests(unittest.TestCase):
    def _git(self, repository: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _repository(self, root: Path) -> tuple[Path, str]:
        dags = root / "pipelines" / "airflow" / "dags"
        dags.mkdir(parents=True)
        (dags / "one.py").write_text("ONE = 1\n", encoding="utf-8")
        (dags / "two.py").write_text("TWO = 2\n", encoding="utf-8")
        self._git(root, "init", "--quiet")
        self._git(root, "config", "user.name", "Babelapha Tests")
        self._git(root, "config", "user.email", "tests@babelapha.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "--quiet", "-m", "fixture")
        return dags, self._git(root, "rev-parse", "HEAD")

    def test_generator_binds_only_the_clean_requested_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            dags, commit = self._repository(repository)
            output = repository / "identity.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--source-dir",
                    str(dags),
                    "--git-commit",
                    commit,
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            identity = json.loads(output.read_text(encoding="utf-8"))
            summary = json.loads(result.stdout)
            self.assertEqual(identity["git_commit"], commit)
            self.assertEqual(summary["bundle_sha256"], identity["bundle_sha256"])
            self.assertEqual(summary["file_count"], 2)
            self.assertEqual(set(identity["files"]), {"one.py", "two.py"})

            mismatch = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--source-dir",
                    str(dags),
                    "--git-commit",
                    "a" * 40,
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("does not match the clean checkout", mismatch.stderr)

            (dags / "one.py").write_text("ONE = 9\n", encoding="utf-8")
            dirty = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--source-dir",
                    str(dags),
                    "--git-commit",
                    commit,
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(dirty.returncode, 0)
            self.assertIn("dirty or unversioned", dirty.stderr)

    def test_deploy_and_local_launchers_publish_and_verify_the_binding(self):
        sync = (ROOT / "docker" / "airflow-gitsync" / "sync-to-airflow.sh").read_text(
            encoding="utf-8"
        )
        identity_publish = sync.index(
            'kubectl cp "${IDENTITY_FILE}" "${AIRFLOW_NAMESPACE}/${COPY_POD_NAME}:${DAGS_FOLDER}/.babelapha-code-identity.json"'
        )
        copy_loop = sync.index('for dag_file in "${SOURCE_PATH}"/*.py; do')
        self.assertGreater(identity_publish, copy_loop)
        self.assertLess(sync.index('echo "  → Copying provenance.py"'), copy_loop)
        self.assertIn('git config --global --add safe.directory "${WORKSPACE_DIR}"', sync)

        teamcity = (ROOT / "ci" / "teamcity" / "settings.kts").read_text(encoding="utf-8")
        airflow_sync = teamcity.split("object MediaPipelineDockerImages", 1)[0]
        self.assertIn("checkoutMode = CheckoutMode.ON_AGENT", airflow_sync)
        self.assertIn("cleanCheckout = true", airflow_sync)

        launcher = (ROOT / "scripts" / "Start-TransparentLocalStack.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("create_code_identity.py", launcher)
        self.assertIn("BABELAPHA_RUNTIME_IMAGE_DIGEST", launcher)
        self.assertIn("docker inspect $container --format '{{.Image}}'", launcher)
        self.assertIn("provenance._git_commit", launcher)
        self.assertIn("org.opencontainers.image.revision", launcher)


if __name__ == "__main__":
    unittest.main()
