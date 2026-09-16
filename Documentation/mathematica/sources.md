# Annotated sources

Sources were reviewed on 2026-09-16. Product behavior and licensing can change;
recheck them before a new runtime upgrade or production decision.

## Current release and recent features

- [Wolfram Language quick revision history](https://www.wolfram.com/language/quick-revision-history/)
  — Version 15.0.1 is the July 2026 maintenance release; Version 15.0 introduced
  the current feature generation.
- [Version 15.0 feature summary](https://reference.wolfram.com/language/guide/SummaryOfNewFeaturesIn150.html)
  — time/event series, tabular and categorical data, model fitting, graph,
  neural-net backend, notebook, compiler, package, and error-handling changes.
- [Version 15 overview](https://www.wolfram.com/language/new-in-15/)
  — official overview of AI Assistant, MCP, notebooks, deployment, and other
  highlighted areas.
- [Structured Package Format](https://reference.wolfram.com/language/tutorial/UsingTheStructuredPackageFormat.html)
  and [PackageInitialize](https://reference.wolfram.com/language/ref/PackageInitialize)
  — Version 15 multi-file package structure selected for the prototype.
- [CatchExceptions](https://reference.wolfram.com/language/ref/CatchExceptions.html)
  — Version 15 typed exception handling used for stable task failure mapping.
- [Wolfram MCP server objects](https://reference.wolfram.com/language/Wolfram/AgentTools/ref/MCPServerObject.html)
  — predefined and custom MCP tool-server surfaces; considered only for a
  later read-only experiment.
- [Standalone Applications](https://reference.wolfram.com/language/StandaloneApplications/)
  — runtime embedding, pruning, and license signatures; a later commercial
  packaging option, not the implemented local runtime.
- [Version 14.3 video update history](https://reference.wolfram.com/language/guide/VideoComputation-UpdateHistory.html)
  — stabilization, feature tracking, point-based object tracking, and
  frame-wise video functions relevant to later media research.
- [Official Wolfram Engine tags](https://hub.docker.com/r/wolframresearch/wolframengine/tags)
  — currently published engine image versions; deployment still pins a digest.

## Wolfram capabilities

- [Natural Language Processing](https://reference.wolfram.com/language/guide/NaturalLanguageProcessing.html.en)
  — text mining, semantic search, classification, clustering, summarization,
  pretrained representations, and LLM-oriented functions.
- [Audio Analysis](https://reference.wolfram.com/language/guide/AudioAnalysis.html)
  — audio measurements, intervals, frequency analysis, speech functions, and
  feature workflows.
- [Video Analysis](https://reference.wolfram.com/language/guide/VideoAnalysis.html)
  — frame/time mapping, object and feature analysis, OCR, tracking, and neural
  network integration.
- [Importing and Exporting Video](https://reference.wolfram.com/language/tutorial/ImportingAndExportingVideo.html)
  — video import/export behavior and the relationship with an installed
  FFmpeg runtime.
- [Graphs and Networks](https://reference.wolfram.com/language/guide/GraphsAndNetworks.html)
  — graph representation, algorithms, measurements, and visualization.
- [Machine Learning](https://reference.wolfram.com/language/guide/MachineLearning.html)
  — classification, regression, clustering, anomaly detection, neural
  networks, and multi-modal feature support.
- [Importing and Exporting](https://reference.wolfram.com/language/guide/ImportingAndExporting.html)
  — portable JSON, data, image, and document interchange.
- [SVG](https://reference.wolfram.com/language/ref/format/SVG.html) and
  [PNG](https://reference.wolfram.com/language/ref/format/PNG.html.en)
  — portable diagnostic-graphic exports.

## Execution and reproducibility

- [WolframScript](https://reference.wolfram.com/language/ref/program/wolframscript.html.en)
  — headless execution of Wolfram Language files, code, functions, and APIs.
- [System Information](https://reference.wolfram.com/language/guide/SystemInformation)
  — kernel version, system identifier, operating system, and machine facts that
  should accompany a result.
- [SeedRandom](https://reference.wolfram.com/language/ref/SeedRandom.html) and
  [BlockRandom](https://reference.wolfram.com/language/ref/BlockRandom.html)
  — explicit and localized pseudorandom state. These do not replace
  cross-version or cross-platform tolerance testing.
- [ExternalEvaluate](https://reference.wolfram.com/language/ref/ExternalEvaluate.html.en)
  — interoperability with Python and other external evaluators. Useful for
  experiments, but unnecessary coupling should not be introduced into the
  canonical pilot calculation.

## Engine, containers, and licensing

- [Wolfram Engine](https://www.wolfram.com/engine/)
  — current downloads, command-line entry points, official container command,
  and developer-engine positioning.
- [Official Wolfram Engine container](https://hub.docker.com/r/wolframresearch/wolframengine)
  — image variants, node-locked activation, on-demand licensing, persistence,
  and kernel-limit considerations.
- [Wolfram Engine FAQ](https://www.wolfram.com/engine/faq/)
  — distinctions among Mathematica, the free engine, prototypes, production,
  organizational outputs, redistribution, and authentication.
- [Commercial license options](https://www.wolfram.com/engine/commercial-options/)
  — local, site, cluster, distribution, cloud, on-demand, and private-cloud
  deployment categories.
- [Free Engine terms](https://www.wolfram.com/legal/terms/wolfram-engine.html)
  — controlling terms for permitted and prohibited free-engine uses. Obtain
  appropriate advice rather than relying only on this summary.

## Babelapha sources of truth

- [`../../contracts/mathematica-local-analysis-input-v2.schema.json`](../../contracts/mathematica-local-analysis-input-v2.schema.json),
  [`../../contracts/mathematica-local-analysis-result-v2.schema.json`](../../contracts/mathematica-local-analysis-result-v2.schema.json),
  and [`../../contracts/mathematica-local-source-evidence-v2.schema.json`](../../contracts/mathematica-local-source-evidence-v2.schema.json)
  — current local media-lab wire contracts.
- [`../../prototype/mathematica/BabelaphaAnalysis/Kernel/init.wl`](../../prototype/mathematica/BabelaphaAnalysis/Kernel/init.wl)
  — current Wolfram package entry point; package files and tests determine what
  is actually implemented.
- [`../pipeline-transparency.md`](../pipeline-transparency.md) — immutable stage
  manifests, evidence bundles, artifact identity, and final provenance gates.
- [`../../contracts/provenance-manifest-v1.schema.json`](../../contracts/provenance-manifest-v1.schema.json)
  — current stage-manifest schema.
- [`../../contracts/provenance-read-api-v1.openapi.json`](../../contracts/provenance-read-api-v1.openapi.json)
  — evidence API and bundle contract.
- [`../../pipelines/airflow/dags/provenance.py`](../../pipelines/airflow/dags/provenance.py)
  — shipped DAG task contracts and provenance implementation.
- [`../../pipelines/airflow/dags/ingest_pipeline_local.py`](../../pipelines/airflow/dags/ingest_pipeline_local.py)
  — current local MinIO/FFmpeg ingestion behavior.
