# Mathematica and Wolfram Language in Babelapha

## Decision

Adopt Mathematica as an **optional research and analysis environment**, not as
a replacement for Babelapha's Python, FFmpeg, Airflow, MinIO, or provenance
stack. Promote a Wolfram analysis into automation only after a bounded pilot
shows a material advantage over the equivalent Python implementation.

The first pilot should use the same versioned Wolfram package from an
interactive notebook and from `wolframscript`. It should analyze an existing
source video together with its verified evidence bundle and produce portable
JSON and PNG/SVG artifacts. The production path remains gated on commercial
licensing.

## Why this boundary

Wolfram Language puts signal processing, statistics, symbolic computation,
machine learning, text processing, graph analysis, media objects, and polished
visualization into one coherent expression system. That makes it particularly
attractive for exploratory work where an analyst moves between several of
those domains.

Babelapha already has stronger operational foundations for ingestion:

- FFmpeg creates HLS and DASH renditions.
- Airflow owns scheduling, retries, and task state.
- MinIO stores versioned inputs, outputs, and immutable evidence.
- the provenance manifests and OpenLineage events identify artifacts and
  execution facts;
- each shipped DAG has a fixed task contract ending in `verify_provenance`.

Putting a licensed Wolfram runtime into the required ingestion path would add
activation and availability failure modes without improving transcoding. A
separate, optional analysis DAG preserves the existing trust boundary.

## Recommended use by workload

| Workload | Recommendation | Reason |
|---|---|---|
| Interactive cross-domain investigation | Pilot | Wolfram's strongest fit: symbolic data, media, graphs, models, and visualizations in one notebook |
| Provenance graph exploration | Pilot | First-class graph algorithms and visualization are useful, but must beat NetworkX/Python in authoring value |
| Audio and speech diagnostics | Pilot | Integrated signal-processing workflow; compare directly with FFmpeg/librosa/SciPy |
| Transcript exploration | Pilot after transcripts exist | Strong text and semantic tools, but model/service dependencies must be made explicit |
| Repeatable derived-artifact stage | Conditional | Viable through `wolframscript` if results are portable, reproducible, licensed, and fully evidenced |
| HLS/DASH transcoding | Do not adopt | FFmpeg remains the correct specialized engine |
| Core orchestration | Do not adopt | Airflow remains the execution authority |
| Canonical provenance storage | Do not adopt | Existing manifests, evidence bundles, MinIO, and OpenLineage remain authoritative |

## Package map

- [Capability assessment](capability-assessment.md)
- [Comparison with the Python stack](python-comparison.md)
- [Target architecture](architecture.md)
- [Pilot design](pilot-design.md)
- [Licensing and operations](licensing-and-operations.md)
- [Annotated sources](sources.md)

## Adoption rule

Move from research-only use to an optional production analysis DAG only when
all of these conditions hold:

1. Wolfram provides a capability or authoring advantage that matters to an
   identified Babelapha user.
2. Notebook and headless runs produce equivalent canonical JSON within stated
   numeric tolerances.
3. Every input, output, code bundle, runtime, model, parameter, and external
   dependency is identifiable in provenance.
4. The output is usable without Mathematica.
5. Resource use is acceptable against the Python baseline.
6. The intended deployment has an approved production license and a workable
   non-interactive activation method.

If any of these conditions fails, keep Mathematica as a local research tool or
reimplement the promoted method in Python.

