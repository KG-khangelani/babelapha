# Current Wolfram features relevant to Babelapha

## Version baseline

This assessment was refreshed on 2026-09-16. The current Wolfram Language
release is **15.0.1** (July 2026). It is a maintenance release containing bug,
stability, and security updates over Version 15.0, which introduced the new
features discussed here. The official Wolfram Engine container currently
publishes a `15.0`/`15.0.0` image; a provenance-bearing run must record the
actual kernel version and immutable image digest rather than infer either from
the tag.

Authoritative release references:

- [Wolfram Language revision history](https://www.wolfram.com/language/quick-revision-history/)
- [Version 15.0 feature summary](https://reference.wolfram.com/language/guide/SummaryOfNewFeaturesIn150.html)
- [Version 15 feature overview](https://www.wolfram.com/language/new-in-15/)
- [Official Wolfram Engine image tags](https://hub.docker.com/r/wolframresearch/wolframengine/tags)

## What v2 actually validates

The local lab separates a feature being available in a recent Wolfram release
from Babelapha having exercised it successfully:

| Wolfram capability | v2 status | Babelapha use |
|---|---|---|
| Version 15 Structured Package Format and `PackageInitialize` | Validated | Multi-file `BabelaphaAnalysis` package |
| Version 15 registered exceptions | Validated | Stable reason and exit-code mapping |
| New-generation named `TimeSeries` and `EventSeries` | Validated | Media measurements and ordered evidence summaries |
| `Tabular` interoperability | Validated | Typed internal evidence table with portable summary |
| First-class `Video`, `Audio`, plots, and spectrograms | Validated | Color, motion, sound, pitch, and notebook visuals |
| Wolfram neural-network repository resource | Validated locally | Pinned and hash-verified Whisper-V1 Tiny CPU inference |
| Rich Mathematica notebook authoring | Validated | Eleven-section `Default.nb` notebook with native media, `DynamicModule` explorers, transcript search, and package-backed input cells |
| `ModelFit`/`ModelFitReport`, semantic retrieval, LLM graphs, MCP, standalone applications, AI Assistant | Not implemented | Separately gated future experiments |

The Whisper cache command is intentionally the only network-enabled step. The
validated analysis result identifies the resource UUID, version, size, three
component hashes, CPU target, greedy sampling, and disabled network mode.

## Used in the Babelapha prototype

### Typed time and event series

Version 15 introduced a new generation of `TimeSeries` and `EventSeries`
objects with named and typed components, missing-data handling, event lookup,
summary operations, and conversions to and from `Tabular`.

This maps naturally to two Babelapha datasets:

- media measurements indexed by playback time, such as loudness, pitch,
  silence, and scene or speaker intervals;
- pipeline events indexed by execution time, such as task attempts, decisions,
  retries, delivery receipts, and artifact publication.

The package builds named media `TimeSeries` values and an evidence
`EventSeries`; the result exports only plain JSON measurements and structural
summaries. Additional Version 15 series operations remain opportunities, not
claims about the current output.

### Tabular and categorical data

`Tabular` arrived in Version 14.2 and Version 15 added richer summaries,
conversions, categorical values, and integration with time/event series.

The v2 package converts the local evidence events into a `Tabular` value and
exports its row/column summary. Richer pipeline evidence columns and categorical
modeling remain follow-on work. Preserve unknown or future values as validation
failures rather than silently recoding them.

This is a better fit than converting canonical evidence into an untyped list
of arbitrary associations, but the evidence bundle remains the source of
truth.

### Explicit model fitting and reports

Version 15 adds `ModelFit`, `ModelFitReport`, and symbolic model structures.
These are useful for explainable run-duration baselines and anomaly research:

- fit duration against input size, media duration, codec, and stage;
- inspect residuals and uncertainty rather than expose an unexplained score;
- export the chosen model structure, parameters, fit criteria, and validation
  measurements into the result contract.

Do not enable automated operational decisions from a fitted model in the first
pilot. The initial output is diagnostic evidence for a human reviewer.

### Structured Package Format and exception handling

Version 15's `PackageInitialize` supports the Structured Package Format, and
the new exception framework provides `CatchExceptions`, `ThrowException`, and
registered exception types.

The prototype uses these features to:

- split input validation, evidence adaptation, media analysis, result export,
  and error mapping into testable package files;
- expose only the package's intended public functions;
- translate typed Wolfram exceptions into stable CLI exit codes and Babelapha
  reason codes;
- return a `Failure`/JSON error document for expected failures while allowing
  unexpected exceptions to fail the task.

This replaces the single large `.wl` package shape suggested in the original
pilot document.

### Notebook and Markdown interoperability

Recent releases support notebook-to-Markdown export, and Version 15 expands
Markdown, Jupyter notebook, and Visual Studio notebook interchange. The current
lab does **not** claim notebook-to-Markdown conversion: Wolfram directly emits
a portable Markdown report and a separate rich `.nb` notebook. Both are review
artifacts listed and hashed in `result.json`.

## Use in later, separately gated experiments

### Video analysis improvements from 14.1–14.3

Recent 14.x releases added or improved `VideoSummaryPlot`, direct audio
operations on video, `VideoTranscribe`, `VideoStabilize`, point-based
`VideoObjectTracking`, feature tracking, frame-wise filters, classification,
and clustering. V2 validates `VideoSummaryPlot`, direct video/audio handling,
and its own sampled-frame color/motion analysis. It does not yet claim
`VideoTranscribe`, stabilization, object tracking, classification, or
clustering. Wolfram video export does not replace Babelapha's FFmpeg rendition
path.

### Semantic retrieval and LLM graphs

Versions 14.1–14.3 added vector-database infrastructure, `SemanticSearch`,
semantic reranking, sentence feature extraction, and `LLMGraph`.

These could support transcript discovery and multi-step research workflows,
but only after the v2 transcript path has representative accuracy evaluation
and a reviewed canonical-sidecar lifecycle. Each embedding model, vector index,
reranker, prompt, provider, and response must be treated as a versioned
dependency or artifact. External LLM output must never be presented as
deterministic evidence.

### Wolfram MCP

Version 15 introduces a Wolfram MCP framework through which external AI clients
can call curated Wolfram tools. A future Babelapha service could expose
read-only tools such as:

- summarize verified run measurements;
- plot a selected artifact's stage timeline;
- compare two evidence-set fingerprints;
- calculate a declared statistic over selected canonical records.

MCP is not a pipeline transport and must not bypass the evidence API. Any
experiment should expose a small allowlisted tool surface, use read-only
credentials, enforce time/resource limits, and return source artifact and
evidence-set identities with every answer.

### Standalone applications

Wolfram's Standalone Applications tooling can package selected Wolfram
functionality behind a C/C++ executable or library with a pruned runtime and
license signatures. It may eventually reduce per-worker activation friction,
but it adds a build, signing, runtime, and commercial licensing path that is
not justified for the first Airflow pilot.

Evaluate it only if a successful pilot needs broad distribution or lower
startup overhead. It is not a workaround for licensing approval.

### AI Assistant in notebooks

Version 15 embeds an AI Assistant in notebooks. It may improve investigator
productivity, but generated code and narrative are proposals until reviewed.
Assistant prompts, providers, and outputs are not part of the deterministic
analysis package and must not be silently introduced into headless runs.

## Features deliberately excluded from the canonical path

- automatic cloud or LLM calls;
- implicit model or paclet downloads;
- MCP write tools;
- notebook-only calculations;
- opaque automated model choice without exported method facts;
- experimental functions without an explicit engine pin and acceptance test;
- Wolfram transcoding in place of FFmpeg.
