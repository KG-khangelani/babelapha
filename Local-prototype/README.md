# Local Mathematica prototype

This workspace keeps the entire Mathematica experiment on the local machine.
Its media inputs and generated products are deliberately excluded from Git.

```text
Local-prototype/
  ingest/       exactly one source video file
  transcripts/  optional local .txt, .srt, or .vtt transcript sidecar
  models/       reserved for workspace-local model manifests or exports
  artefacts/    verified source identity, analysis input, and runtime identity
  output/       canonical JSON, plots, reports, and the rich notebook
  logs/         timestamped PowerShell, Python, and Wolfram execution logs
  work/         local fixtures and scratch products for analysis stages
```

The launcher creates the runtime directories when they do not exist. To place
a media file before the first run, create `ingest/` explicitly, then launch
the analysis from the repository root:

```powershell
New-Item -ItemType Directory -Force .\Local-prototype\ingest | Out-Null
Copy-Item C:\path\to\video.mp4 .\Local-prototype\ingest\
.\scripts\Invoke-MathematicaLocalPrototype.ps1
```

The default transcript mode is `prefer_sidecar`: a matching local `.txt`,
`.srt`, or `.vtt` file in `transcripts/` wins; otherwise the package uses the
verified local Wolfram Whisper V1 Tiny cache. Model acquisition is an explicit,
one-time online preparation step. The subsequent analysis remains offline:

```powershell
# One-time cache and SHA-256 verification while online
.\scripts\Invoke-MathematicaLocalPrototype.ps1 -PrepareSpeechModelOnly

# Normal local run; no model download is attempted
.\scripts\Invoke-MathematicaLocalPrototype.ps1 -TranscriptMode prefer_sidecar
```

Wolfram stores the fetched resource in its local object store; `models/` is a
workspace reservation for future exported model manifests or copies, not a
second implicit cache.

Use `-TranscriptMode automatic` to require the cached model,
`-TranscriptMode sidecar` to require a sidecar, or
`-TranscriptMode disabled` to make the omission explicit. If the selected
source is unavailable, the notebook still renders the transcript section with
an auditable reason.

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

The production boundary itself has no third-party Python dependency. The test
suite requires `jsonschema` so validation of the published v2 contracts cannot
be silently skipped:

```powershell
python -m pip install -r .\prototype\mathematica\requirements-test.txt
python -m unittest tests.test_mathematica_local_boundary -v
$runtime = .\scripts\Invoke-MathematicaLocalPrototype.ps1 -PreflightOnly |
  ConvertFrom-Json
& $runtime.wolframscript_path -local $runtime.wolfram_kernel_path `
  -file .\prototype\mathematica\tests\run-tests.wls
```

The notebook is a review surface, not a raw result dump. A successful export
must visibly include an executive summary, storyboard, color and motion
analytics, sound analytics, transcript/speech status, a synchronized
cross-modal timeline, capability coverage, methodology, and reproducibility
evidence. If a transcript or local speech model is absent, the transcript
section remains present and explains the exact limitation instead of silently
disappearing.

The current notebook has eleven major sections and embeds the analytical
graphics directly: six KPI cards, all twelve sampled frames, dominant colors,
RGB/brightness trajectories, motion and scene-change candidates, waveform,
RMS/peak/loudness curves, spectral centroid/spread, zero-crossing rate,
fundamental-frequency candidates, spectrogram, audible/silent intervals,
transcript statistics, a shared cross-modal timeline, provenance, output
inventory, capability coverage, methodology, and a package-backed rerun cell.

Everything under `ingest/`, `transcripts/`, `models/`, `artefacts/`, `output/`,
`logs/`, and `work/` stays local and is ignored by Git except for the directory
placeholders. The pushed prototype consists of the package, launcher,
contracts, tests, and documentation—not the personal media or generated
analysis products.
