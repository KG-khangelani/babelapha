# Local Mathematica prototype

This workspace keeps the entire Mathematica experiment on the local machine.
Its media inputs and generated products are deliberately excluded from Git.

```text
Local-prototype/
  ingest/       exactly one source video file
  artefacts/    verified source identity, analysis input, and runtime identity
  output/       canonical JSON, plots, review material, and the notebook
  logs/         timestamped PowerShell, Python, and Wolfram execution logs
  work/         reserved local scratch space for later analysis stages
```

The launcher creates the runtime directories when they do not exist. To place
a media file before the first run, create `ingest/` explicitly, then launch
the analysis from the repository root:

```powershell
New-Item -ItemType Directory -Force .\Local-prototype\ingest | Out-Null
Copy-Item C:\path\to\video.mp4 .\Local-prototype\ingest\
.\scripts\Invoke-MathematicaLocalPrototype.ps1
```

The launcher discovers installed Wolfram products, tests each candidate
through `wolframscript -local`, selects a working Version 15-or-newer kernel,
and records its exact identity. Python hashes the complete Wolfram package
before execution; that digest is bound into the run ID and must match the hash
independently computed by Wolfram and returned in the result. Override
discovery without changing global WolframScript configuration when necessary:

```powershell
.\scripts\Invoke-MathematicaLocalPrototype.ps1 `
  -WolframKernelPath 'H:\Program Files\Wolfram Research\Wolfram Engine\15.0\WolframKernel.exe'
```

Use `-PreflightOnly` to inspect the selected local runtime without creating or
changing anything inside the workspace. The main run rejects zero, multiple,
or unsupported ingest files. It then prepares the local integrity contract,
runs the Wolfram test suite, invokes the Wolfram analysis, independently
validates its portable outputs, and verifies that both canonical JSON and a
Mathematica notebook were produced.

The audio window and silence detector are directly tunable for local
experiments; the exact values become part of the deterministic run identity:

```powershell
.\scripts\Invoke-MathematicaLocalPrototype.ps1 `
  -SilenceThresholdDb -45 `
  -FrameSeconds 0.05 `
  -HopSeconds 0.025 `
  -RandomSeed 20260916
```

Add `-VerifyRepeatability` when you want the launcher to execute the full
analysis twice and require identical canonical result hashes. Because the
canonical result includes every declared artifact hash, this also proves the
notebook, reports, and plots were byte-identical across the two runs. The
verification record is written to `artefacts/repeatability.json`.

Python is limited to boundary validation. The media import, measurements,
visualizations, report, and notebook are all produced by the local Wolfram
kernel. The workflow does not start Airflow, MinIO, Pachyderm, or any cloud
service.
