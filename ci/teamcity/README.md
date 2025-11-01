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

## Troubleshooting Qodana

### Empty Results or Exit Code 137 (OOMKilled)

**Symptom**: Qodana step completes quickly with empty artifact containing only directory scaffolding; agent logs show container terminated with exit code 137.

**Root Cause**: The Qodana container exceeds memory limits during Python interpreter configuration and skeleton generation. Kubernetes OOMKiller terminates the container before it can produce results.

**Solution**:

1. **Increase memory allocation** in the TeamCity Qodana build step:
   - Navigate to Build Configuration → Steps → Qodana → Docker Settings
   - Add to "Additional docker run arguments": `--memory=4g --memory-swap=4g`
   - For larger projects, use 6GB+ (`--memory=6g --memory-swap=6g`)

2. **Verify Kubernetes pod limits**:

   ```bash
   kubectl -n teamcity describe pod <agent-pod-name>
   kubectl -n teamcity top pod <agent-pod-name>
   ```

3. **Optimize `qodana.yaml`**:
   - Ensure `bootstrap: minimal` is set (reduces memory footprint)
   - Add heavy directories to `exclude` list (docker/, ci/, pachyderm/, etc.)

4. **Monitor the run**:

   ```bash
   kubectl -n teamcity logs -f <agent-pod-name>
   kubectl -n teamcity exec <agent-pod-name> -- docker stats
   ```

### License or Image Issues

If you see "license" errors or "unsupported linter" messages, ensure `qodana.yaml` specifies `linter: jetbrains/qodana-python-community:latest` (the free community edition).
