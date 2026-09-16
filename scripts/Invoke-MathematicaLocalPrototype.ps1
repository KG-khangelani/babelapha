[CmdletBinding()]
param(
    [string]$Workspace,
    [string]$WolframScriptPath,
    [string]$WolframKernelPath,
    [version]$MinimumWolframVersion = [version]"15.0",
    [ValidateRange(-120.0, 0.0)]
    [double]$SilenceThresholdDb = -40.0,
    [ValidateScript({ $_ -gt 0.0 -and $_ -le 10.0 })]
    [double]$FrameSeconds = 0.04,
    [ValidateScript({ $_ -gt 0.0 -and $_ -le 10.0 })]
    [double]$HopSeconds = 0.02,
    [ValidateRange(0, 2147483647)]
    [int]$RandomSeed = 20260916,
    [switch]$SkipWolframTests,
    [switch]$VerifyRepeatability,
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
if ($HopSeconds -gt $FrameSeconds) {
    throw "HopSeconds must not exceed FrameSeconds."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = Join-Path $repoRoot "Local-prototype"
}
$workspaceRoot = [System.IO.Path]::GetFullPath($Workspace)
$prototypeRoot = Join-Path $repoRoot "prototype\mathematica"
$boundaryScript = Join-Path $prototypeRoot "local_boundary.py"
$analysisScript = Join-Path $prototypeRoot "analyze.wls"
$testScript = Join-Path $prototypeRoot "tests\run-tests.wls"

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [string]$ExplicitPath
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $candidate = [System.IO.Path]::GetFullPath($ExplicitPath)
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "$Name was not found at the explicit path: $candidate"
        }
        return $candidate
    }

    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $command) {
        throw "$Name is not available on PATH and no explicit path was supplied."
    }
    return $command.Source
}

function Get-WolframKernelCandidates {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $resolved = [System.IO.Path]::GetFullPath($ExplicitPath)
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "WolframKernel was not found at the explicit path: $resolved"
        }
        return ,([pscustomobject]@{
            Path = $resolved
            Product = "explicit"
            ProductVersion = [version]"0.0"
            Explicit = $true
        })
    }

    $candidates = [System.Collections.Generic.List[object]]::new()
    $installationRoots = @(
        "HKLM:\SOFTWARE\Wolfram Research\Installations",
        "HKLM:\SOFTWARE\WOW6432Node\Wolfram Research\Installations",
        "HKCU:\SOFTWARE\Wolfram Research\Installations"
    )
    foreach ($installationRoot in $installationRoots) {
        if (-not (Test-Path -LiteralPath $installationRoot)) {
            continue
        }
        foreach ($installation in Get-ChildItem -LiteralPath $installationRoot -ErrorAction SilentlyContinue) {
            $properties = Get-ItemProperty -LiteralPath $installation.PSPath
            $executableProperty = $properties.PSObject.Properties['ExecutablePath']
            if ($null -eq $executableProperty -or [string]::IsNullOrWhiteSpace($executableProperty.Value)) {
                continue
            }
            $directory = Split-Path -Parent ([string]$executableProperty.Value)
            foreach ($executableName in @("WolframKernel.exe", "wolfram.exe")) {
                $kernelPath = Join-Path $directory $executableName
                if (Test-Path -LiteralPath $kernelPath -PathType Leaf) {
                    $productVersion = [version]"0.0"
                    $productVersionProperty = $properties.PSObject.Properties['ProductVersion']
                    if ($null -ne $productVersionProperty -and -not [string]::IsNullOrWhiteSpace($productVersionProperty.Value)) {
                        $productVersion = [version]$productVersionProperty.Value
                    }
                    $productNameProperty = $properties.PSObject.Properties['ProductName']
                    $productName = if ($null -eq $productNameProperty) { "Wolfram product" } else { [string]$productNameProperty.Value }
                    $candidates.Add([pscustomobject]@{
                        Path = (Resolve-Path -LiteralPath $kernelPath).Path
                        Product = $productName
                        ProductVersion = $productVersion
                        Explicit = $false
                    })
                    break
                }
            }
        }
    }

    $programFilesRoots = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($drive in Get-PSDrive -PSProvider FileSystem) {
        if (-not [string]::IsNullOrWhiteSpace($drive.Root)) {
            [void]$programFilesRoots.Add((Join-Path $drive.Root "Program Files\Wolfram Research"))
        }
    }
    foreach ($programFilesRoot in $programFilesRoots) {
        if (-not (Test-Path -LiteralPath $programFilesRoot -PathType Container)) {
            continue
        }
        foreach ($productDirectory in Get-ChildItem -LiteralPath $programFilesRoot -Directory) {
            foreach ($versionDirectory in Get-ChildItem -LiteralPath $productDirectory.FullName -Directory) {
                $kernelPath = Join-Path $versionDirectory.FullName "WolframKernel.exe"
                if (-not (Test-Path -LiteralPath $kernelPath -PathType Leaf)) {
                    continue
                }
                $version = [version]"0.0"
                if ($versionDirectory.Name -match '^\d+(\.\d+){0,3}$') {
                    $version = [version]$versionDirectory.Name
                }
                $candidates.Add([pscustomobject]@{
                    Path = (Resolve-Path -LiteralPath $kernelPath).Path
                    Product = $productDirectory.Name
                    ProductVersion = $version
                    Explicit = $false
                })
            }
        }
    }

    return @(
        $candidates |
            Group-Object Path |
            ForEach-Object { $_.Group | Select-Object -First 1 } |
            Sort-Object -Property @(
                @{ Expression = { if ($_.Product -match 'Engine') { 0 } else { 1 } }; Descending = $false },
                @{ Expression = "ProductVersion"; Descending = $true },
                @{ Expression = "Path"; Descending = $false }
            )
    )
}

function Resolve-WolframRuntime {
    param(
        [Parameter(Mandatory)] [string]$ScriptPath,
        [string]$ExplicitKernelPath,
        [Parameter(Mandatory)] [version]$MinimumVersion
    )

    $probeCode = 'ExportString[<|"version"->$Version,"versionNumber"->$VersionNumber,"releaseNumber"->$ReleaseNumber,"systemID"->$SystemID,"processorType"->$ProcessorType|>,"RawJSON","Compact"->True]'
    $failures = [System.Collections.Generic.List[string]]::new()
    $kernelCandidates = @(Get-WolframKernelCandidates -ExplicitPath $ExplicitKernelPath)
    if ($kernelCandidates.Count -eq 0) {
        throw "No local Wolfram kernel installation was discovered. Supply -WolframKernelPath."
    }

    foreach ($candidate in $kernelCandidates) {
        $probeOutput = @(& $ScriptPath -local $candidate.Path -code $probeCode 2>&1)
        $probeExitCode = $LASTEXITCODE
        $jsonLine = $probeOutput |
            ForEach-Object { [string]$_ } |
            Where-Object { $_.TrimStart().StartsWith('{') } |
            Select-Object -Last 1
        if ($probeExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($jsonLine)) {
            $failures.Add("$($candidate.Path) (exit $probeExitCode)")
            if ($candidate.Explicit) {
                break
            }
            continue
        }

        try {
            $identity = $jsonLine | ConvertFrom-Json -ErrorAction Stop
            if ([string]$identity.version -notmatch '^(\d+\.\d+(?:\.\d+)?)') {
                throw "The Wolfram version string has no semantic version prefix."
            }
            $runtimeVersion = [version]$Matches[1]
        }
        catch {
            $failures.Add("$($candidate.Path) (unparseable identity)")
            if ($candidate.Explicit) {
                break
            }
            continue
        }
        if ($runtimeVersion -lt $MinimumVersion) {
            $failures.Add("$($candidate.Path) (runtime $runtimeVersion is older than $MinimumVersion)")
            if ($candidate.Explicit) {
                break
            }
            continue
        }

        return [pscustomobject]@{
            KernelPath = $candidate.Path
            Product = $candidate.Product
            RegistryProductVersion = $candidate.ProductVersion.ToString()
            Version = [string]$identity.version
            VersionNumber = [double]$identity.versionNumber
            ReleaseNumber = [int]$identity.releaseNumber
            SystemID = [string]$identity.systemID
            ProcessorType = [string]$identity.processorType
        }
    }

    $failureSummary = $failures -join '; '
    throw "No working local Wolfram $MinimumVersion-or-newer kernel was found. Attempts: $failureSummary"
}

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory)] [string]$Label,
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [string]$LogPath
    )

    $header = "[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString("o"), $Label
    Add-Content -LiteralPath $LogPath -Value $header -Encoding utf8NoBOM
    Write-Host "==> $Label"
    & $FilePath @Arguments 2>&1 |
        Tee-Object -FilePath $LogPath -Append |
        ForEach-Object { Write-Host $_ }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode. See $LogPath"
    }
}

$effectiveWolframScriptPath = $WolframScriptPath
if ([string]::IsNullOrWhiteSpace($effectiveWolframScriptPath)) {
    $effectiveWolframScriptPath = [Environment]::GetEnvironmentVariable(
        "BABELAPHA_WOLFRAMSCRIPT_PATH",
        "Process"
    )
}
$effectiveKernelPath = $WolframKernelPath
if ([string]::IsNullOrWhiteSpace($effectiveKernelPath)) {
    $effectiveKernelPath = [Environment]::GetEnvironmentVariable(
        "BABELAPHA_WOLFRAM_KERNEL_PATH",
        "Process"
    )
}

$wolframScript = Resolve-CommandPath -Name "wolframscript" -ExplicitPath $effectiveWolframScriptPath
$runtime = Resolve-WolframRuntime `
    -ScriptPath $wolframScript `
    -ExplicitKernelPath $effectiveKernelPath `
    -MinimumVersion $MinimumWolframVersion
$python = Resolve-CommandPath -Name "python" -ExplicitPath $null

$preflight = [ordered]@{
    status = "READY"
    local_only = $true
    media_backend = "wolfram-import"
    wolframscript_path = $wolframScript
    wolfram_kernel_path = $runtime.KernelPath
    wolfram_version = $runtime.Version
    wolfram_system_id = $runtime.SystemID
    wolfram_processor_type = $runtime.ProcessorType
    python_path = $python
}

if ($PreflightOnly) {
    $preflight | ConvertTo-Json -Depth 4
    return
}

foreach ($requiredFile in @($boundaryScript, $analysisScript, $testScript)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required prototype entry point is missing: $requiredFile"
    }
}

& $python $boundaryScript init --workspace $workspaceRoot
if ($LASTEXITCODE -ne 0) {
    throw "Could not initialize the local prototype workspace."
}

$ingestDirectory = Join-Path $workspaceRoot "ingest"
$ingestFiles = @(
    Get-ChildItem -LiteralPath $ingestDirectory -File -Force |
        Where-Object { $_.Name -notin @('.gitignore', '.gitkeep') }
)
if ($ingestFiles.Count -eq 0) {
    throw "Place exactly one video file in $ingestDirectory."
}
if ($ingestFiles.Count -ne 1) {
    $names = ($ingestFiles.Name | Sort-Object) -join ', '
    throw "The ingest directory must contain exactly one media file; found $($ingestFiles.Count): $names"
}
$supportedExtensions = @('.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi')
if ($ingestFiles[0].Extension.ToLowerInvariant() -notin $supportedExtensions) {
    throw "Unsupported local video extension '$($ingestFiles[0].Extension)'. Supported: $($supportedExtensions -join ', ')"
}

$logDirectory = Join-Path $workspaceRoot "logs"
[void](New-Item -ItemType Directory -Path $logDirectory -Force)
$runStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$logPath = Join-Path $logDirectory "mathematica-local-$runStamp.log"

$prepareArguments = @(
    $boundaryScript,
    "prepare",
    "--workspace", $workspaceRoot,
    "--silence-threshold-db", $SilenceThresholdDb.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--frame-seconds", $FrameSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--hop-seconds", $HopSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--random-seed", $RandomSeed.ToString([Globalization.CultureInfo]::InvariantCulture)
)

Invoke-LoggedCommand `
    -Label "Prepare verified local analysis input" `
    -FilePath $python `
    -Arguments $prepareArguments `
    -LogPath $logPath

$artefactsDirectory = Join-Path $workspaceRoot "artefacts"
$analysisInput = Join-Path $artefactsDirectory "analysis-input.json"
$runtimeManifest = Join-Path $artefactsDirectory "runtime.json"
$gitCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    $gitCommit = $null
}
$runtimeRecord = [ordered]@{
    schema_version = "1.0.0"
    recorded_at = (Get-Date).ToUniversalTime().ToString("o")
    local_only = $true
    workspace = $workspaceRoot
    source_path = $ingestFiles[0].FullName
    git_commit = $gitCommit
    wolfram = [ordered]@{
        wolframscript_path = $wolframScript
        kernel_path = $runtime.KernelPath
        version = $runtime.Version
        version_number = $runtime.VersionNumber
        release_number = $runtime.ReleaseNumber
        system_id = $runtime.SystemID
        processor_type = $runtime.ProcessorType
        media_backend = "Wolfram Language Import"
    }
    python = [ordered]@{
        executable = $python
        role = "input and output contract boundary only"
    }
    analysis_parameters = [ordered]@{
        silence_threshold_db = $SilenceThresholdDb
        frame_seconds = $FrameSeconds
        hop_seconds = $HopSeconds
        random_seed = $RandomSeed
    }
    repeatability_requested = [bool]$VerifyRepeatability
}
$runtimeRecord |
    ConvertTo-Json -Depth 6 |
    Set-Content -LiteralPath $runtimeManifest -Encoding utf8NoBOM

if (-not $SkipWolframTests) {
    Invoke-LoggedCommand `
        -Label "Run Wolfram package tests" `
        -FilePath $wolframScript `
        -Arguments @("-local", $runtime.KernelPath, "-file", $testScript) `
        -LogPath $logPath
}

Invoke-LoggedCommand `
    -Label "Run local Mathematica analysis" `
    -FilePath $wolframScript `
    -Arguments @("-local", $runtime.KernelPath, "-file", $analysisScript, "--input", $analysisInput) `
    -LogPath $logPath

Invoke-LoggedCommand `
    -Label "Validate and canonicalize Mathematica outputs" `
    -FilePath $python `
    -Arguments @($boundaryScript, "validate", "--workspace", $workspaceRoot) `
    -LogPath $logPath

$outputDirectory = Join-Path $workspaceRoot "output"
$resultPath = Join-Path $outputDirectory "result.json"
$repeatabilityVerified = $false
if ($VerifyRepeatability) {
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
        throw "The first canonical result is missing before repeatability verification: $resultPath"
    }
    $firstResultHash = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()

    Invoke-LoggedCommand `
        -Label "Re-prepare identical input for repeatability verification" `
        -FilePath $python `
        -Arguments $prepareArguments `
        -LogPath $logPath
    Invoke-LoggedCommand `
        -Label "Repeat local Mathematica analysis" `
        -FilePath $wolframScript `
        -Arguments @("-local", $runtime.KernelPath, "-file", $analysisScript, "--input", $analysisInput) `
        -LogPath $logPath
    Invoke-LoggedCommand `
        -Label "Validate repeated Mathematica outputs" `
        -FilePath $python `
        -Arguments @($boundaryScript, "validate", "--workspace", $workspaceRoot) `
        -LogPath $logPath

    $secondResultHash = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($secondResultHash -ne $firstResultHash) {
        throw "Repeatability verification failed: canonical result hashes differ ($firstResultHash vs $secondResultHash)."
    }
    $repeatabilityRecord = [ordered]@{
        schema_version = "1.0.0"
        verified = $true
        run_count = 2
        canonical_result_sha256 = $secondResultHash
        verified_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $repeatabilityRecord |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $artefactsDirectory "repeatability.json") -Encoding utf8NoBOM
    $repeatabilityVerified = $true
}

if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
    throw "The validated canonical result is missing: $resultPath"
}
$notebooks = @(Get-ChildItem -LiteralPath $outputDirectory -Filter "*.nb" -File)
if ($notebooks.Count -eq 0) {
    throw "The Mathematica run did not produce a notebook in $outputDirectory."
}

[ordered]@{
    status = "COMPLETE"
    workspace = $workspaceRoot
    source = $ingestFiles[0].FullName
    result = $resultPath
    notebooks = @($notebooks.FullName)
    runtime_manifest = $runtimeManifest
    log = $logPath
    wolfram_version = $runtime.Version
    wolfram_kernel = $runtime.KernelPath
    repeatability_verified = $repeatabilityVerified
} | ConvertTo-Json -Depth 5
