# Capability assessment

## What Mathematica brings

The relevant product distinction is between **Mathematica**, which includes
the notebook interface, and the **Wolfram Engine**, which can execute the same
language headlessly. The architectural opportunity is therefore not two
separate implementations: it is one Wolfram package used interactively during
discovery and invoked by `wolframscript` after promotion.

### Cross-domain symbolic workflow

Wolfram Language represents datasets, graphs, audio, video, images, statistical
models, units, dates, and symbolic expressions as values that compose through
the same language. This is the principal differentiator for Babelapha. An
investigator can move from a run manifest to a graph, join that graph to media
measurements, fit a model, and render an explanation without coordinating
several libraries and object models.

This convenience is valuable for discovery. It does not by itself make a
Wolfram implementation more reproducible or operationally safer.

## Workload assessment

### Transcript and language analysis

Implemented v2 baseline:

- `prefer_sidecar` discovers and SHA-256-binds a matching local `.txt`, `.srt`,
  or `.vtt` transcript; `sidecar`, `automatic`, and `disabled` make the desired
  behavior explicit;
- automatic mode uses the pinned Wolfram Whisper-V1 Tiny encoder, decoder, and
  labels only after their cached bytes have been verified;
- inference is local, greedy, CPU-targeted, and records model and inference
  provenance; normal analysis runs with network access disabled;
- audio is materialized, mixed to mono, split by sample index, and zero-padded
  to deterministic 30-second model inputs instead of relying on the failing
  `AudioPartition` pad path;
- text, timestamped segments, word/sentence counts, lexical diversity, top
  terms, and words per minute are emitted in the v2 result and notebook.

The validated reference run produced a coherent 29-word Whisper transcript for
the local ten-second interview clip using the verified resource UUID/version
and three verified model components. This proves the local mechanism for that
clip, not transcript accuracy for every accent, language, or recording
condition.

Potential value:

- language identification, tokenization, grammatical structure, entity-like
  text extraction, classification, clustering, summarization, and semantic
  search;
- rapid combination of text features with statistics and visualizations;
- built-in access to pretrained representations and LLM-oriented functions.

Risks and limits:

- transcript sidecars remain user-supplied local inputs; the ingestion DAG does
  not produce them;
- the Whisper cache step requires a deliberate one-time online acquisition,
  and cached-resource identity must remain pinned and verified;
- LLM and semantic functions would still introduce separate model, service,
  credential, and nondeterminism concerns and are not used here;
- language coverage and accuracy must be tested on the actual interview
  languages and recording conditions rather than inferred from API breadth.

Verdict: **validated for a local research transcript path**. Keep sidecar and
Whisper provenance distinct, evaluate accuracy on representative interviews,
and treat future model- or service-backed operations as separately identified
processors.

### Audio and speech diagnostics

Implemented v2 baseline:

- global and overlapping-window RMS, peak, and loudness measurements;
- crest factor, local dynamic range, RMS/dBFS distributions, audible/silent
  intervals, spectral centroid/spread, zero-crossing rate, and pitch coverage;
- waveform, diagnostic curves, and spectrogram embedded in the notebook;
- per-feature availability instead of invented values when a measurement is
  not meaningful.

Potential value:

- first-class audio objects, trimming, filtering, resampling, loudness and
  interval measurements;
- spectrogram, periodogram, cepstrogram, pitch, and feature workflows;
- direct transition from signal measurements to statistical and visual
  analysis.

Risks and limits:

- FFmpeg and Python libraries already cover much of the same ground;
- codec behavior may still depend on the host and FFmpeg installation;
- pitch and speech recognition remain signal/model dependent and require
  coverage and accuracy evaluation rather than a blanket “available” claim.

Verdict: **implemented and validated as the strongest local Mathematica use
case so far**. It creates visible, inspectable results while retaining explicit
feature availability and portable summaries.

### Video-frame analysis

Implemented v2 baseline:

- twelve uniformly sampled frames, contact sheet, and `VideoSummaryPlot`;
- per-frame RGB, brightness, saturation, contrast, colorfulness, motion, and
  color-histogram distance;
- an eight-color deterministic palette and thresholded scene-change
  candidates;
- shared-time alignment with audio and transcript evidence.

Potential value:

- first-class video import, track and frame extraction, mapping over time,
  feature detection, object tracking, OCR, and visualization;
- concise prototyping across video, image, audio, and model operations.

Risks and limits:

- decoding and encoding are not a reason to replace FFmpeg;
- frame analysis can be memory-intensive and should sample or stream rather
  than materialize a long interview in memory;
- pretrained network identity and model-resource availability must be pinned
  or recorded.

Verdict: **implemented for selective sampled-frame research**, not routine
media packaging or a replacement for the FFmpeg rendition path.

### Provenance and operational analysis

Potential value:

- convert evidence-bundle runs, stages, and artifact observations into
  first-class graphs;
- compute communities, centrality, paths, connected components, and anomaly
  features;
- combine topology with task duration and integrity measurements in a notebook.

Risks and limits:

- NetworkX, pandas, and common visualization libraries already satisfy many
  graph-analysis needs without a commercial runtime;
- graph visualization must preserve evidence semantics rather than becoming a
  second source of truth;
- the evidence bundle, not a notebook export, remains canonical.

Verdict: **good research use, weak standalone justification for production**.

### Statistics, machine learning, and symbolic modeling

Potential value:

- high-level classification, prediction, clustering, anomaly detection,
  dimensionality reduction, distribution fitting, uncertainty, and symbolic
  formula discovery;
- rapid movement between exact symbolic work and numerical estimation;
- compact model inspection and publication-quality graphics.

Risks and limits:

- automated method selection can obscure the chosen algorithm unless it is
  extracted and recorded;
- random seeds are necessary but not sufficient for reproducibility across
  engine, platform, hardware, and model-resource changes;
- Python has broader MLOps integration and a larger pool of deployable model
  tooling.

Verdict: **valuable when symbolic reasoning or cross-domain composition is
central**. Benchmark ordinary ML tasks against the Python stack before
adoption.

## Capability classification

Every candidate function used in a pilot must be classified before execution:

| Class | Examples | Evidence required |
|---|---|---|
| Local deterministic | parsing, explicit transforms, exact graph algorithms | engine version, system ID, code hash, parameters |
| Local numeric | filters, measurements, numerical models | above plus precision, tolerances, library/codec facts |
| Seeded stochastic | clustering or learned procedures using randomness | above plus seed, random method, selected algorithm |
| Downloaded resource | neural nets, paclets, curated datasets | resource name, version/digest, acquisition state |
| External service | LLM, cloud, or connected service operations | provider/model, request parameters, response identity where available, policy approval |

The lab prefers the first two classes. Whisper is the one current downloaded
resource: acquisition is explicit, its component bytes are verified, and the
subsequent processor records disabled network mode. An external service must
never be silently reached from a supposedly local or reproducible analysis.
