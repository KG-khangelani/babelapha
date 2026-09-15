# Provenance contracts

`provenance-manifest-v1.schema.json` is the canonical, versioned contract for
one completed Airflow task attempt. Records are append-only and are stored at:

```text
provenance/<object-id>/<dag-run-id>/<task-id>/<attempt>-<status>.json
```

The task callbacks emit the same run, decision, input, output, code, and
container identities as OpenLineage events. `reports/<object-id>/*.json` files
remain mutable operational summaries for compatibility; they are not the
provenance source of truth.

Integrity is explicit. An artifact with a SHA-256 is `VERIFIED`; a source that
could not be hashed is `UNVERIFIED`. Likewise, a container is
`VERIFIED_DIGEST` only when the runtime image is identified by a registry
digest. A tag alone is recorded as `CONFIGURED_REF_ONLY` and must never be
presented as exact reproducibility.
