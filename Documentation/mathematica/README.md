# Local Mathematica media lab

## Status

The Wolfram-first local prototype is implemented and has completed an
end-to-end video run. The package requires Wolfram Language 15 or newer. The
verified runtime for this checkout is **Wolfram Engine 15.0.0 for Windows
x86-64**; every run records the exact kernel path and version rather than
assuming a patch release.

The primary entry point is:

```powershell
.\scripts\Invoke-MathematicaLocalPrototype.ps1
```

Place exactly one video in `Local-prototype/ingest/`. The launcher discovers a
working local kernel, runs the Wolfram tests and analysis, validates the result,
and keeps all runtime material under `Local-prototype/`.

## Local boundary

Mathematica owns the analysis:

- direct `Video` import and audio-track extraction;
- sampled-frame brightness, color, and motion analysis;
- RMS amplitude, peak amplitude, EBU loudness, spectral centroid, and
  audible/silent interval analysis;
- named-component `TimeSeries`, provenance `EventSeries`, and `Tabular` data;
- plots, reports, and a reproducible Mathematica notebook.

Python is deliberately limited to the trust boundary. It hashes the source,
writes strict local evidence and analysis input, rejects ambiguous JSON and
unsafe paths, independently rehashes every result artifact, and canonicalizes
`result.raw.json` as `result.json`. It does not calculate the media results or
produce the human-facing analysis.

The Version 15 package uses Structured Package Format through
`PackageInitialize` and registered typed exceptions. Expected failures map to
stable reason codes and process exit codes.

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

## Documentation map

- [Local workspace and command](../../Local-prototype/README.md)
- [Implemented pilot](pilot-design.md)
- [Local architecture](architecture.md)
- [Mathematica leverage roadmap](leverage-roadmap.md)
- [Capability assessment](capability-assessment.md)
- [Current and recent features](new-features.md)
- [Comparison framework](python-comparison.md)
- [Licensing and operations](licensing-and-operations.md)
- [Annotated sources](sources.md)

## Deferred production path

Airflow, MinIO publication, containerized Wolfram execution, OpenLineage
emission, MCP, cloud services, LLMs, and speech services are not part of this
implemented prototype. They remain possible later phases only after the local
Mathematica work establishes a concrete analytical advantage and its licensing
and operational model is approved.
