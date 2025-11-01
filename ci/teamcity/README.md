# TeamCity Configuration

This directory holds the TeamCity Kotlin DSL that defines CI pipelines for the
project. The `Media Pipeline Checks` build configuration validates the Airflow
and Pachyderm assets before we add heavier integration tests.

## Bootstrapping

1. Enable Kotlin DSL in your TeamCity project.
2. Point the settings repository to this Git repository/branch.
3. On the first run TeamCity will automatically provision the build steps
   defined in `settings.kts`.

The scripts currently create throwaway virtual environments to keep the agent
clean. Replace them with cached environments or containerized steps when the CI
usage grows.

## Qodana (Static Analysis)

This repository includes a `qodana.yaml` at the repo root configured to use the
community Python linter image. In TeamCity, add the "Qodana" build step to any
build configuration (e.g., your `Babelapha_AirflowGitSync` config) and leave the
"Configuration file" field empty; the step will automatically discover
`qodana.yaml` from the checkout directory.

Notes:

- We exclude heavy and non-source folders to keep analysis fast on Kubernetes agents.
- The linter image is `jetbrains/qodana-python-community:latest` to avoid license issues.
- `failThreshold` is currently permissive to avoid failing the pipeline while we
   stabilize rules; reduce to `0` later to fail the build on any reported problem.

Troubleshooting on Kubernetes agents:

- If the Qodana step fails immediately, check that the agent can pull Docker
   images from `docker.io/jetbrains` or `ghcr.io/jetbrains` depending on your
   registry mirror policy.
- Inspect the TeamCity agent pod logs for image pull errors, permission issues,
   or ephemeral storage exhaustion.

Kubernetes agents note:

- The TeamCity Qodana step runs the linter in a Docker container. Your agent
   must have access to a Docker daemon (DinD sidecar with `--privileged`, or a
   Docker/Podman socket). If your Kubernetes agent image doesn't provide this,
   either add a Docker-enabled agent or use Qodana Cloud with a `QODANA_TOKEN`.
