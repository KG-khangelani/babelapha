# Local Mathematica media lab

## Status

The Wolfram-first local prototype is implemented as
`mathematica-local-media-lab-v2` and has completed an independently validated
end-to-end video run. The reference run exercised color, motion, sound, pitch,
spectral, transcript, and cross-modal analysis and produced the rich
thirteen-section notebook. The package requires Wolfram Language 15 or newer.
The verified runtime for this checkout is **Wolfram Engine 15.0.0 for Windows
x86-64**; every run records the exact kernel path and version rather than
assuming a patch release.

The primary entry point is:

```powershell
.\scripts\Invoke-MathematicaLocalPrototype.ps1
```

Place exactly one video in `Local-prototype/ingest/`. The launcher discovers a
working local kernel, runs the Wolfram tests and analysis, validates the result,
and keeps all runtime material under `Local-prototype/`.

The default transcript mode, `prefer_sidecar`, uses a hash-bound local `.txt`,
`.srt`, or `.vtt` file when one matches the source. Otherwise it uses a
previously cached and verified **Wolfram Whisper-V1 Tiny** resource. Model
acquisition is a separate, explicit online preparation action; analysis then
runs with Wolfram internet access disabled:

```powershell
.\scripts\Invoke-MathematicaLocalPrototype.ps1 -PrepareSpeechModelOnly
.\scripts\Invoke-MathematicaLocalPrototype.ps1 -TranscriptMode prefer_sidecar
```

## Local boundary

Mathematica owns the analysis:

- direct `Video` import and audio-track extraction;
- sampled-frame brightness, RGB, saturation, contrast, colorfulness, palette,
  histogram-distance, motion, and scene-change analysis;
- RMS and peak amplitude, EBU loudness, dynamic range, spectral centroid and
  spread, zero-crossing rate, fundamental-frequency candidates, spectrogram,
  and audible/silent interval analysis;
- verified local Whisper Tiny inference or verified transcript-sidecar parsing,
  transcript statistics, deterministic 30-second audio preparation, and
  timestamped navigation segments with explicit timing provenance;
- one shared media-time instrument aligning visual, sound, scene, speech, and
  cross-modal event evidence;
- named-component `TimeSeries`, provenance `EventSeries`, and `Tabular` data;
- plots, reports, and a reproducible thirteen-section Mathematica notebook with
  native video playback, one linked frame/audio/speech/scene/event cursor,
  transcript search, evidence-backed observations, and executable setup/rerun
  cells.

Python is deliberately limited to the trust boundary. It hashes the source,
writes strict local evidence and analysis input, rejects ambiguous JSON and
unsafe paths, independently rehashes every result artifact, and canonicalizes
`result.raw.json` as `result.json`. It does not calculate the media results or
produce the human-facing analysis.

The Version 15 package uses Structured Package Format through
`PackageInitialize` and registered typed exceptions. Expected failures map to
stable reason codes and process exit codes.

The current wire contracts are the three `mathematica-local-*-v2` schemas.
The v1 schemas remain checked in as immutable historical contracts and are
superseded, not rewritten.

## Portable outputs

Each successful Wolfram run declares and hashes exactly seven analytical
artifacts:

1. `audio-overview.png`
2. `audio-overview.svg`
3. `video-contact-sheet.png`
4. `video-summary.png`
5. `report.md`
6. `report.html`
7. `analysis-notebook.nb`

The output directory also contains Wolfram's `result.raw.json` and Python's
strictly validated canonical `result.json`.

Open `analysis-notebook.nb` in the Wolfram Notebook front end, not through the
PDF or HTML preview, to use its native controls. The notebook uses standard
`Default.nb` styles and references the local video under `Local-prototype/ingest/`
for playback.

## Documentation map

- [Local workspace and command](../../Local-prototype/README.md)
- [Implemented pilot](pilot-design.md)
- [Local architecture](architecture.md)
- [Notebook sections](notebook-sections.md)
- [Mathematica leverage roadmap](leverage-roadmap.md)
- [Capability assessment](capability-assessment.md)
- [Current and recent features](new-features.md)
- [Comparison framework](python-comparison.md)
- [Licensing and operations](licensing-and-operations.md)
- [Annotated sources](sources.md)

## Deferred production path

Airflow, MinIO publication, containerized Wolfram execution, OpenLineage
emission, MCP, cloud services, LLMs, and external speech services are not part
of this implemented prototype. They remain possible later phases only after
the local Mathematica work establishes a concrete analytical advantage and its
licensing and operational model is approved.
