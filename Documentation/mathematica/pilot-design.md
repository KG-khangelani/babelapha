# Implemented local Mathematica pilot

## Objective and verified baseline

The pilot is now a runnable, local-only media laboratory rather than a design
for a future Airflow task. It exercises Wolfram Language directly over one
local video while retaining portable, independently verified outputs.

The package requires Wolfram Language 15 or newer. The completed reference run
used **Wolfram Engine 15.0.0 for Microsoft Windows (64-bit)** on
`Windows-x86-64`. The launcher records the exact runtime in
`Local-prototype/artefacts/runtime.json` for every run.

## Run it

```powershell
New-Item -ItemType Directory -Force .\Local-prototype\ingest | Out-Null
Copy-Item C:\path\to\video.mp4 .\Local-prototype\ingest\
.\scripts\Invoke-MathematicaLocalPrototype.ps1
```

The ingest directory must contain exactly one supported video. Use
`-PreflightOnly` to inspect the selected kernel without changing the workspace,
or pass `-WolframKernelPath` to select an installed kernel explicitly.

```text
Local-prototype/
  ingest/       one user-supplied video
  artefacts/    source evidence, analysis input, and runtime identity
  output/       raw/canonical JSON, plots, reports, and notebook
  logs/         combined launcher, Python, and Wolfram logs
  work/         reserved scratch space for later local experiments
```

All five runtime directories are ignored by Git. The workspace guide is
[Local-prototype/README.md](../../Local-prototype/README.md).

## Execution flow

```mermaid
flowchart LR
    V[One local video] --> P[Python prepare boundary]
    P --> E[Source evidence and analysis input]
    E --> T[Wolfram package tests]
    T --> W[Wolfram media analysis]
    W --> R[result.raw.json]
    W --> A[Seven analysis artifacts]
    R --> G[Python result gate]
    A --> G
    G --> C[Canonical result.json]
```

The PowerShell launcher always invokes `wolframscript -local` with the exact
discovered kernel path. It does not change global WolframScript configuration
and does not start Docker, Airflow, MinIO, Pachyderm, or a cloud service.

## Implementation shape

```text
prototype/mathematica/
  BabelaphaAnalysis/Kernel/
    init.wl
    ErrorMapping.wl
    InputValidation.wl
    EvidenceAdapter.wl
    MediaAnalysis.wl
    ResultExport.wl
    PublicAPI.wl
  analyze.wls
  local_boundary.py
  tests/
    BabelaphaAnalysisTests.wlt
    run-tests.wls
```

- `init.wl` initializes the Version 15 Structured Package Format package with
  `PackageInitialize`.
- Registered exception types distinguish invalid input, integrity,
  dependencies, analysis runtime, and export failures.
- `analyze.wls` is a thin CLI over the exported package function. The generated
  notebook calls that same package and contains no private calculation path.
- `local_boundary.py` is dependency-free Python and owns only source identity,
  strict contracts, safe paths, output rehashing, and canonical JSON.

## Mathematica workload

The package opens the source directly as a Wolfram `Video`, samples twelve
uniform frames, and constructs a named `TimeSeries` for brightness and
mean-absolute grayscale frame difference. It calculates frame dimensions,
brightness statistics, mean RGB, and motion summaries, then exports a contact
sheet and `VideoSummaryPlot` result.

For videos with a decodable audio track, Wolfram extracts `Audio[video]` and
uses `AudioMeasurements`, `AudioLocalMeasurements`, `AudioIntervals`,
`AudioPlot`, and `Spectrogram`. Results include sample rate, channel count,
duration, RMS/peak amplitude, EBU loudness, audible and silent intervals, and
spectral-centroid statistics. Local RMS and centroid observations are combined
into a named-component `TimeSeries`.

The verified source events become an `EventSeries` and a `Tabular` object.
These rich Wolfram values remain internal; portable JSON contains their stable
summaries.

## Contracts and artifacts

The Python preparation step writes canonical
`artefacts/source-evidence.json` and `artefacts/analysis-input.json`. Their
versioned schemas define source SHA-256 and byte size, local object/run
identity, the exact Wolfram package SHA-256, fixed analysis parameters,
evidence identity, and the relative output directory. The run ID changes when
the source, parameters, analysis, or package changes. Mathematica independently
recomputes the package hash and rechecks source/evidence hashes before analysis.

Wolfram produces `result.raw.json` plus these seven declared outputs:

| Artifact | Purpose |
|---|---|
| `audio-overview.png` | Waveform, RMS, spectral-centroid, and spectrogram review |
| `audio-overview.svg` | Portable vector RMS and spectral-centroid view |
| `video-contact-sheet.png` | Uniformly sampled source frames |
| `video-summary.png` | Wolfram `VideoSummaryPlot` output |
| `report.md` | Portable text report with measurements and capabilities |
| `report.html` | Self-contained local review page referencing the plots |
| `analysis-notebook.nb` | Mathematica review notebook and shared-package rerun cell |

Python then validates exact keys and types, rejects duplicate/nonfinite JSON,
ensures every output is a direct child of `output/`, checks the exact seven-file
set and media types, recomputes every size and SHA-256, and writes canonical
`result.json` with `SORTED_INDENTED_JSON_V1`.

## Failure and acceptance behavior

| Condition | Behavior |
|---|---|
| Missing, multiple, or unsupported ingest files | Launcher/boundary fails before Wolfram analysis |
| Invalid input or unsafe relative path | Typed input failure, exit code 10 |
| Source/evidence identity mismatch | Typed integrity failure, exit code 11 |
| Required Wolfram capability unavailable | Typed dependency failure, exit code 12 |
| Media analysis or export failure | Typed runtime/export failure, exit code 20 |
| Invalid raw result or output hash | Python rejects it and does not write canonical `result.json` |

The implemented end-to-end run passed Wolfram package tests, direct video and
audio analysis, seven-artifact export, independent Python canonicalization,
and a two-run byte-for-byte repeatability gate. A separate local no-audio run
also passed with explicit `UNAVAILABLE` capability evidence, null audio
measurements, portable placeholder plots, and a valid custom-workspace
notebook.
Further local experiments should preserve these contracts or introduce a new
versioned `analysis_id` and schemas.
