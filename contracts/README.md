# Provenance contracts

`provenance-manifest-v1.schema.json` is the canonical, versioned contract for
one completed Airflow task attempt. Records are append-only and are stored at:

```text
provenance/<object-id>/<dag-run-id>/<task-id>/<attempt>-<status>.json
```

The task callbacks emit the same run, decision, input, output, code, and
container identities as OpenLineage events. The execution fields use
`openlineage-babelapha-execution-run-facet-v2.schema.json`; every input and
output dataset uses `openlineage-babelapha-artifact-dataset-facet-v1.schema.json`.
The event schema URLs are pinned to the Git commit containing those contracts,
not to a mutable branch.

Every event is first stored immutably in an OpenLineage outbox. A successful
HTTP delivery creates a separate immutable acknowledgement conforming to
`openlineage-delivery-receipt-v1.schema.json`:

```text
openlineage/outbox/<object-id>/<dag-run-id>/<task-id>/<attempt>-<status>.json
openlineage/delivered/<object-id>/<dag-run-id>/<task-id>/<attempt>-<status>.json
```

An outbox object without its matching delivery receipt is pending and can be
replayed without rebuilding or changing the original event.

`provenance-read-api-v1.openapi.json` versions the read-only explorer boundary.
Version `1.7.0` adds a scoped evidence-bundle endpoint containing the exact
validated canonical manifest, queued-event, and delivery-receipt documents,
each bound to its immutable storage URI, SHA-256, and explicit document
canonicalization. Version `1.6.0` added exact delivery-receipt hashes and a deterministic
`evidence_set` SHA-256 over the complete selected manifest and lineage snapshot.
Version `1.5.1` additionally rejects reuse of one manifest ID by multiple task
attempts, preventing an ambiguous manifest-to-lineage join. Version `1.5.0`
added storage-bound manifest evidence to every stage attempt:
the canonical manifest SHA-256 and full OpenLineage outbox/receipt identity are
available alongside the decision. The reader rejects non-canonical bytes,
misplaced manifests, and false manifest self-links. Version `1.4.0` added
opt-in, per-item catalog evidence summaries derived from the strict detail
reader. The catalog can therefore expose readable items,
missing evidence, and integrity conflicts before selection without maintaining
an independent status store. The boundary also provides an ordered
stage-evidence ledger plus verified run-level and artifact-level identities.
Consumers do not have to infer task topology, retries, missing evidence, or
artifact reuse from an unordered set of manifests. Contradictory run facts or
competing identities for the same artifact URI fail the read boundary.

Unknown-to-known legacy identity gaps remain readable as `PARTIAL` and name
their missing fields. Immutable-contract violations and competing known facts
are surfaced by the HTTP API as `409 EVIDENCE_INTEGRITY_FAILED`.

`reports/<object-id>/*.json` files remain mutable operational summaries for
compatibility; they are not the provenance source of truth.

Integrity is explicit. An artifact with a SHA-256 is `VERIFIED`; a source that
could not be hashed is `UNVERIFIED`. Likewise, a container is
`VERIFIED_DIGEST` only when the runtime image is identified by a registry
digest. A tag alone is recorded as `CONFIGURED_REF_ONLY` and must never be
presented as exact reproducibility.

The contract regression tests freeze both the commit-pinned emitted URLs and
the exact checked-in schema bytes. Changing a contract therefore requires a
new schema version and immutable contract commit; editing a v1 file in place
fails validation.

## Local Mathematica analysis contracts

The Wolfram-first local prototype has a separate, filesystem-scoped contract
set. It does not depend on Airflow, MinIO, or the provenance read API:

### Current v2 media-lab contracts

- `mathematica-local-source-evidence-v2.schema.json` identifies the one local
  source video, an optional verified transcript sidecar, and the ordered
  discovery/hash-verification events;
- `mathematica-local-analysis-input-v2.schema.json` binds that evidence,
  source, optional sidecar, transcript mode, analysis parameters, and Wolfram
  package SHA-256 to `mathematica-local-media-lab-v2` and a deterministic run
  identity;
- `mathematica-local-analysis-result-v2.schema.json` defines the processor,
  source/input identity, color/motion/sound/pitch/transcript/cross-modal
  measurements, summarized `TimeSeries`/`EventSeries`/`Tabular` structures,
  per-capability status, provenance summary, and output identities.

Transcript mode is one of `automatic`, `prefer_sidecar`, `sidecar`, or
`disabled`. A selected `.txt`, `.srt`, or `.vtt` sidecar is a first-class input:
its relative path, format, SHA-256, and byte size are checked before Wolfram
analysis. A Whisper-produced transcript must instead carry the pinned model
resource identity, verified component bytes, and local inference facts. The
result validator rejects a method/provenance mismatch, invented text on an
unavailable transcript, and a `USED` transcript capability without its
required source or model evidence.

The pinned automatic path is Wolfram `Whisper-V1 Nets`, UUID
`5211d691-293f-417d-a19f-f1e5faef3fb7`, resource version `1.0.0`, size `Tiny`.
Acquisition is an explicit cache-preparation action. A normal analysis run has
network access disabled and cannot silently fetch the model.

### Superseded v1 contracts

The original files remain available for historical results and regression
tests:

- `mathematica-local-source-evidence-v1.schema.json` identifies one local
  source video and its ordered discovery/hash-verification events;
- `mathematica-local-analysis-input-v1.schema.json` binds that source and
  evidence to `mathematica-local-media-lab-v1` and the original parameters;
- `mathematica-local-analysis-result-v1.schema.json` defines the original
  video/audio summary, capabilities, provenance, and seven outputs.

V1 is superseded by v2; it is not deleted or edited in place. Consumers must
select a validator by `schema_version` and `analysis_id`, never interpret a v1
document as if it contained v2 transcript or extended-media evidence.

`prototype/mathematica/local_boundary.py` writes canonical v2 source evidence
and analysis input before Wolfram runs. After Mathematica writes
`output/result.raw.json`, the same boundary rejects unknown fields, duplicate
keys, nonfinite values, unsafe paths, identity mismatches, and missing or
altered outputs. It also requires the eleven notebook section markers and at
least five embedded graphics. It recomputes the SHA-256 and byte size for the
exact seven declared Wolfram artifacts:

```text
analysis-notebook.nb
audio-overview.png
audio-overview.svg
report.html
report.md
video-contact-sheet.png
video-summary.png
```

Only then does it write `output/result.json` using
`SORTED_INDENTED_JSON_V1`. Python is the contract and integrity boundary; all
media/transcript measurements and the seven analytical artifacts are produced
by the local Wolfram package. The validated v2 reference run used Wolfram
Engine 15.0.0 on Windows x86-64, reported `network_mode: disabled`, and returned
`USED` for every core capability, including local Whisper transcription. That
is local validation evidence, not a claim that the v2 lab is deployed in an
Airflow or other production runtime.
