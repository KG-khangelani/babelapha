# Annotated sources

Sources were reviewed on 2026-09-16. Product behavior and licensing can change;
recheck them when the pilot starts and before a production decision.

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
