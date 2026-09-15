[CmdletBinding()]
param(
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dagDirectory = Join-Path $repoRoot "pipelines\airflow\dags"
$identityPath = Join-Path $dagDirectory ".babelapha-code-identity.json"
$identityGenerator = Join-Path $repoRoot "pipelines\airflow\create_code_identity.py"

Push-Location $repoRoot
$previousGitSha = [Environment]::GetEnvironmentVariable("BABELAPHA_GIT_SHA", "Process")
$previousRuntimeDigest = [Environment]::GetEnvironmentVariable(
    "BABELAPHA_RUNTIME_IMAGE_DIGEST",
    "Process"
)
try {
    $gitSha = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $gitSha -notmatch '^[a-f0-9]{40}$|^[a-f0-9]{64}$') {
        throw "Could not resolve a full Git commit SHA for the local DAG bundle."
    }

    & python $identityGenerator `
        --source-dir $dagDirectory `
        --git-commit $gitSha `
        --output $identityPath
    if ($LASTEXITCODE -ne 0) {
        throw "The DAG bundle is dirty, unversioned, or does not match Git commit $gitSha."
    }

    $env:BABELAPHA_GIT_SHA = $gitSha
    if (-not $SkipBuild) {
        & docker compose build airflow-webserver provenance-api
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose could not build the Airflow and provenance API images."
        }
    }

    $runtimeImageId = (& docker image inspect babelapha-airflow-local --format '{{.Id}}').Trim()
    if ($LASTEXITCODE -ne 0 -or $runtimeImageId -notmatch '^sha256:[a-f0-9]{64}$') {
        throw "Could not resolve the exact babelapha-airflow-local image ID."
    }
    $env:BABELAPHA_RUNTIME_IMAGE_DIGEST = $runtimeImageId

    & docker compose up -d --force-recreate
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose could not start the transparent local stack."
    }

    foreach ($container in @(
        "babelapha-airflow-webserver",
        "babelapha-airflow-scheduler",
        "babelapha-airflow-dag-processor"
    )) {
        $actualImageId = (& docker inspect $container --format '{{.Image}}').Trim()
        if ($LASTEXITCODE -ne 0 -or $actualImageId -ne $runtimeImageId) {
            throw "$container is not running the attested Airflow image $runtimeImageId."
        }
        $containerEnvironment = & docker inspect $container --format '{{range .Config.Env}}{{println .}}{{end}}'
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect $container runtime identity."
        }
        if ($containerEnvironment -notcontains "BABELAPHA_GIT_SHA=$gitSha") {
            throw "$container did not receive the attested Git commit."
        }
        if ($containerEnvironment -notcontains "BABELAPHA_RUNTIME_IMAGE_DIGEST=$runtimeImageId") {
            throw "$container did not receive the verified runtime image digest."
        }
    }

    $runtimeGitCommit = (& docker exec babelapha-airflow-webserver python -c "import sys; sys.path.insert(0, '/opt/airflow/dags'); import provenance; print(provenance._git_commit(source_dir='/opt/airflow/dags') or '')").Trim()
    if ($LASTEXITCODE -ne 0 -or $runtimeGitCommit -ne $gitSha) {
        throw "The running Airflow code bundle did not verify Git commit $gitSha."
    }

    $apiRevision = (& docker inspect babelapha-provenance-api --format '{{index .Config.Labels "org.opencontainers.image.revision"}}').Trim()
    if ($LASTEXITCODE -ne 0 -or $apiRevision -ne $gitSha) {
        throw "The provenance API image revision does not match Git commit $gitSha."
    }

    Write-Output "Transparent local stack is running with verified identities."
    Write-Output "Git commit: $gitSha"
    Write-Output "Airflow image: $runtimeImageId"
    Write-Output "DAG identity: $identityPath"
}
finally {
    [Environment]::SetEnvironmentVariable("BABELAPHA_GIT_SHA", $previousGitSha, "Process")
    [Environment]::SetEnvironmentVariable(
        "BABELAPHA_RUNTIME_IMAGE_DIGEST",
        $previousRuntimeDigest,
        "Process"
    )
    Pop-Location
}
