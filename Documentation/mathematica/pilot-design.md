# Pilot design

## Objective

Determine whether Wolfram Language provides enough analytical and authoring
value to justify an optional Babelapha compute stage while preserving portable
outputs, reproducibility, and artifact-level provenance.

The pilot is a design for later execution. This documentation change does not
install or activate Wolfram products.

## Workload

Run an **audio and provenance diagnostic** over one short, legally usable test
video already accepted by the local ingestion pipeline.

The shared analysis package will:

1. consume a bundle that Babelapha's existing Python verifier has accepted;
2. confirm that the selected source identity matches the verified input
   manifest;
3. inspect media duration, sample rate, and channel count;
4. calculate loudness summary statistics and detected audio/silence intervals;
5. calculate a deterministic spectrogram-derived summary;
6. render an audio overview plot;
7. summarize the ingestion stage/artifact graph without changing its meaning;
8. emit a canonical JSON result and PNG/SVG diagnostics.

Speech recognition, LLM calls, pretrained neural networks, and cloud functions
are excluded from the first pilot. They can be evaluated later as separately
identified processors.

## Shared implementation shape

```text
prototype/mathematica/
  Kernel/BabelaphaAnalysis.wl
  analyze.wls
  notebooks/audio-provenance-pilot.nb
  tests/BabelaphaAnalysisTests.wlt
  fixtures/
```

- `BabelaphaAnalysis.wl` contains all calculation and export functions.
- The notebook imports the package and presents intermediate exploration.
- `analyze.wls` is a thin command-line adapter that reads an input manifest,
  calls the package, and writes outputs.
- Tests call package functions directly. The notebook contains no unique
  production calculation.

This layout is illustrative until the pilot is authorized; it is not created
as part of the architecture-report phase.

## Input interface

The headless entry point accepts one path to a UTF-8 JSON document:

```json
{
  "schema_version": "1.0.0",
  "analysis_id": "audio-provenance-diagnostic-v1",
  "object_id": "sample-001",
  "ingestion_run_id": "manual__example",
  "evidence_bundle_uri": "http://provenance-api:8010/api/v1/media/sample-001/evidence-bundle?run_id=manual__example",
  "evidence_verification": {
    "verification": "VERIFIED",
    "verifier": "pipelines/airflow/verify_evidence_bundle.py",
    "verifier_sha256": "<64 lowercase hexadecimal characters>",
    "evidence_set_sha256": "<64 lowercase hexadecimal characters>"
  },
  "source": {
    "uri": "s3://pachyderm/incoming/sample-001/sample.mp4",
    "sha256": "<64 lowercase hexadecimal characters>",
    "s3_version_id": "<version identifier>"
  },
  "parameters": {
    "random_seed": 20260916,
    "spectrogram_window_seconds": 0.04,
    "silence_threshold_db": -40.0
  },
  "output_directory": "/work/output"
}
```

The adapter rejects unknown top-level fields, a missing source digest or
storage version, a missing `VERIFIED` result from
`verify_evidence_bundle.py`, a mismatched verifier or evidence-set hash, a
mismatch between that verified bundle and the selected source, and an
unsupported analysis or schema version. Airflow captures the verifier's JSON
result in a separate pre-analysis task so evidence verification does not depend
on Wolfram availability.

## Result interface

`result.json` is the canonical analysis output. Its initial contract contains:

```json
{
  "schema_version": "1.0.0",
  "analysis_id": "audio-provenance-diagnostic-v1",
  "object_id": "sample-001",
  "ingestion_run_id": "manual__example",
  "processor": {
    "wolfram_version": "<exact kernel version>",
    "system_id": "<Wolfram system identifier>",
    "package_sha256": "<sha256>",
    "random_seed": 20260916
  },
  "source": {
    "uri": "s3://pachyderm/incoming/sample-001/sample.mp4",
    "sha256": "<sha256>",
    "s3_version_id": "<version identifier>"
  },
  "measurements": {
    "duration_seconds": 0.0,
    "sample_rate_hz": 0,
    "channel_count": 0,
    "loudness": {},
    "audio_intervals": [],
    "silence_intervals": [],
    "spectrogram_summary": {}
  },
  "provenance_summary": {
    "evidence_set_sha256": "<sha256>",
    "task_count": 0,
    "artifact_count": 0,
    "integrity_conflict_count": 0
  },
  "outputs": [
    {"path": "audio-overview.png", "media_type": "image/png", "sha256": "<sha256>"},
    {"path": "audio-overview.svg", "media_type": "image/svg+xml", "sha256": "<sha256>"}
  ]
}
```

All numeric units are encoded in field names or documented contract metadata;
Wolfram-specific expressions are not exposed in JSON. JSON serialization uses
sorted keys and a single documented number-format policy before hashing.

## Python baseline

Build an equivalent reference implementation using FFmpeg/ffprobe, Python,
NumPy/SciPy, librosa where needed, NetworkX, and Matplotlib. It receives the
same input manifest and emits the same measurement definitions.

The comparison records:

- implementation time to the first reviewable result;
- source lines excluding fixtures and generated material;
- cold and warm wall-clock time;
- peak resident memory;
- repeat-run canonical JSON hashes;
- numeric differences for agreed measurements;
- notebook-to-headless equivalence;
- dependency, activation, and recovery steps;
- reviewer assessment of clarity and analytical expressiveness.

## Acceptance tests

1. **Input integrity:** altered source bytes, storage version, or evidence-set
   hash cause a failure before analysis.
2. **Repeatability:** three headless runs with identical inputs produce the
   same canonical JSON hash; image hashes may vary only if the reason is
   documented and the underlying plotted data hash is stable.
3. **Notebook/headless parity:** canonical measurements produced through the
   notebook and CLI match exactly for integers/strings and within `1e-9`
   relative or absolute tolerance for floating-point fields.
4. **Cross-stack parity:** Wolfram and Python measurements agree within the
   field-specific tolerance documented before the benchmark. Differences in
   algorithm semantics are named rather than hidden by a broad tolerance.
5. **Portability:** results can be inspected and verified using only JSON,
   standard image viewers, and Babelapha's Python verifier.
6. **Isolation:** unavailable Wolfram licensing fails only the optional pilot
   DAG and does not affect ingestion artifacts or status.
7. **Provenance:** every successful task attempt records input/output hashes,
   code and image identity, parameters, runtime version, and dependency facts;
   the final analysis provenance gate passes.
8. **Network control:** the declared local run succeeds with outbound network
   access disabled after required resources and license arrangements are in
   place.

## Adoption decision

Use the weighted scorecard in [python-comparison.md](python-comparison.md).
Regardless of score, the pilot is a no-go for production if portable outputs,
provenance completeness, commercial licensing, or unattended activation fails.
