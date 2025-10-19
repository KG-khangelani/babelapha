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
