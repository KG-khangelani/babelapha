# Pipeline transparency

Babelapha records one immutable provenance manifest for every Airflow task
attempt. Airflow remains the operational view, MinIO/Pachyderm stores the
evidence, and Marquez renders the OpenLineage graph.

```mermaid
flowchart LR
    U[Source object] --> H[Inspect and hash]
    H --> S[Virus scan]
    S --> V[Media validation]
    V --> T[Transcode and upload]
    T --> Q[Verify stored outputs]

    H --> P[(Immutable manifests)]
    S --> P
    V --> P
    T --> P
    Q --> P

    P --> O[OpenLineage events]
    O --> M[Marquez API and graph]
```

## Canonical record

The schema is [`contracts/provenance-manifest-v1.schema.json`](../contracts/provenance-manifest-v1.schema.json).
The immutable object key is:

```text
provenance/<object-id>/<dag-run-id>/<task-id>/<attempt>-<status>.json
```

Every record carries:

- the object ID and filename;
- Airflow DAG, run, task, attempt, status, timing, and log URL;
- an explicit decision outcome, machine-readable reason code, and message;
- input and output URIs, SHA-256 values, byte sizes, S3 version IDs, ETags,
  and optional Pachyderm commit IDs;
- repository commit, exact DAG-file SHA-256, configured image, and registry
  digest when available.

`reports/<object-id>/*.json` files are mutable operational summaries retained
for compatibility. They are not the provenance source of truth.

## Failure and retry semantics

Successful, failed, and retrying attempts use different immutable keys. A
retry therefore preserves the failed attempt instead of overwriting it. The
Airflow callbacks never overwrite a non-identical existing record. Both the
local and production DAGs end with a `verify_provenance` task; a successful
pipeline cannot pass that gate when any required upstream success manifest is
missing.

The write uses the S3 `If-None-Match: *` precondition, so append-only behavior
is atomic even when duplicate callbacks race. Re-emitting identical bytes is
idempotent; conflicting bytes are rejected.

## Exact identity

Artifacts are marked `VERIFIED` only when their bytes were hashed. MinIO object
versioning is enabled by the local stack, and transcoded objects carry their
SHA-256 in S3 metadata before they are read back and verified.

Container identity is deliberately honest:

- `image@sha256:<digest>` produces `VERIFIED_DIGEST`;
- a mutable tag such as `localhost/transcode:latest` produces
  `CONFIGURED_REF_ONLY`.

For production, set these variables to digest-pinned references:

```text
BABELAPHA_SCAN_IMAGE=registry.example/clamav@sha256:<64 hex>
BABELAPHA_VALIDATE_IMAGE=registry.example/validate@sha256:<64 hex>
BABELAPHA_TRANSCODE_IMAGE=registry.example/transcode@sha256:<64 hex>
```

For local Airflow, inject the result of `docker image inspect` as
`BABELAPHA_RUNTIME_IMAGE_DIGEST` when exact container reproduction is required.
Set `BABELAPHA_GIT_SHA` to the full 40- or 64-character commit SHA. Short or
symbolic refs are not accepted as exact identities. The DAG-file SHA-256 remains
exact even in an uncommitted local working tree. The production DAG sync also
writes the validated CI commit to `.babelapha-git-sha` beside the deployed DAGs,
so a copied DAG retains its exact Git identity even when the Airflow pod does
not contain the repository metadata.

## Production runtime wiring

The Airflow scheduler, workers, triggerer, and webserver must receive the same
runtime configuration. Keep credentials in Kubernetes Secrets and the
non-secret values in the Airflow deployment configuration:

| Variable | Production value |
|---|---|
| `S3_BUCKET`, `MINIO_ENDPOINT` | Source/output bucket and its S3-compatible endpoint |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Kubernetes Secret required by the production DAG |
| `PROVENANCE_S3_BUCKET` | Versioned bucket containing the canonical records |
| `PROVENANCE_S3_ENDPOINT` | Pachyderm/MinIO S3-compatible API endpoint |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Optional separate Secret with write access to the provenance prefix |
| `OPENLINEAGE_URL` | Marquez API base URL |
| `OPENLINEAGE_ENDPOINT` | `/api/v1/lineage` |
| `OPENLINEAGE_NAMESPACE` | Stable environment name such as `babelapha-production` |
| `BABELAPHA_*_IMAGE` | Registry references pinned with `@sha256:` |

The sync job refuses a missing, short, or symbolic `BUILD_VCS_NUMBER`. Container
references without a digest remain usable, but their manifests are explicitly
marked `CONFIGURED_REF_ONLY` rather than exact.

## OpenLineage and Marquez

The same manifest identity, run/stage/attempt/status/timing, decision, Git and
DAG identity, container identity, orchestration details, and artifact evidence
are emitted to OpenLineage. Every input and output dataset carries its SHA-256,
byte size, media type, integrity state, Pachyderm commit, S3 version, and ETag in
the versioned `babelapha_artifact` input/output facet. Placing this evidence in
`inputFacets` and `outputFacets` preserves it on the dataset version associated
with that exact run. Schema URLs are pinned to the exact contract commit rather
than the mutable default branch.

Events are sent to:

```text
POST http://marquez:5000/api/v1/lineage
```

The Compose stack exposes:

- Airflow: <http://localhost:8080>
- MinIO console: <http://localhost:9001>
- Marquez API: <http://localhost:5000>
- Marquez lineage UI: <http://localhost:3001>

Select one media item and inspect every recorded run, stage decision, failure,
artifact hash, storage version, Pachyderm commit, Git commit, DAG hash, and
container digest with:

```powershell
docker compose run --rm provenance-inspect --object-id <object-id>
```

Restrict the view to one Airflow run or return machine-readable JSON:

```powershell
docker compose run --rm provenance-inspect --object-id <object-id> --run-id <run-id>
docker compose run --rm provenance-inspect --object-id <object-id> --format json
```

Run the contract tests and configuration check with:

```powershell
python -m unittest discover -s tests -v
docker compose config --quiet
```

The future public explorer should query these canonical records. It must not
create a second status model or infer provenance from logs.
