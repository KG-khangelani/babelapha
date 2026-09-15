from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProvenanceAPIImageContractTests(unittest.TestCase):
    def test_image_is_pinned_minimal_non_root_and_self_contained(self):
        dockerfile = (ROOT / "docker" / "provenance-api" / "Dockerfile").read_text(
            encoding="utf-8"
        )

        self.assertRegex(
            dockerfile,
            re.compile(r"^FROM python:3\.11\.16-slim-bookworm@sha256:[a-f0-9]{64}$", re.MULTILINE),
        )
        self.assertIn('org.opencontainers.image.revision="${BUILD_VCS_NUMBER}"', dockerfile)
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        for source in (
            "pipelines/airflow/dags/provenance.py",
            "pipelines/airflow/inspect_provenance.py",
            "pipelines/airflow/provenance_api.py",
            "contracts/provenance-read-api-v1.openapi.json",
        ):
            self.assertIn(f"COPY {source}", dockerfile)
        self.assertNotIn("apache/airflow", dockerfile.lower())

    def test_every_runtime_python_dependency_is_exactly_pinned(self):
        requirements = (
            ROOT / "docker" / "provenance-api" / "requirements.txt"
        ).read_text(encoding="utf-8").splitlines()

        self.assertGreater(len(requirements), 0)
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                self.assertRegex(requirement, r"^[a-z0-9-]+==[^=\s]+$")

    def test_compose_and_teamcity_build_the_standalone_image(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        teamcity = (ROOT / "ci" / "teamcity" / "settings.kts").read_text(
            encoding="utf-8"
        )

        self.assertIn("dockerfile: docker/provenance-api/Dockerfile", compose)
        self.assertIn("image: babelapha-provenance-api-local", compose)
        self.assertIn('path = "docker/provenance-api/Dockerfile"', teamcity)
        self.assertIn("BUILD_VCS_NUMBER=%build.vcs.number%", teamcity)
        for trigger in (
            "+:docker/provenance-api/**",
            "+:pipelines/airflow/provenance_api.py",
            "+:pipelines/airflow/inspect_provenance.py",
            "+:pipelines/airflow/dags/provenance.py",
            "+:contracts/provenance-read-api-v1.openapi.json",
        ):
            self.assertIn(trigger, teamcity)


if __name__ == "__main__":
    unittest.main()
