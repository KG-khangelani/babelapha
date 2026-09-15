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
Version `1.1.0` adds an ordered stage-evidence ledger to each run so consumers
do not have to infer task topology, retries, or missing evidence from an
unordered set of manifests.

`reports/<object-id>/*.json` files remain mutable operational summaries for
compatibility; they are not the provenance source of truth.

Integrity is explicit. An artifact with a SHA-256 is `VERIFIED`; a source that
could not be hashed is `UNVERIFIED`. Likewise, a container is
`VERIFIED_DIGEST` only when the runtime image is identified by a registry
digest. A tag alone is recorded as `CONFIGURED_REF_ONLY` and must never be
presented as exact reproducibility.
