# Licensing and operations

## Licensing posture

The free Wolfram Engine is suitable for pre-production development,
prototyping, demos, and testing under its terms. Wolfram's current FAQ states
that production applications and organizational output generation require an
appropriate license. Babelapha must therefore treat the free engine as a pilot
tool, not as a production entitlement.

Before any production deployment, obtain written confirmation that the chosen
license covers:

- unattended execution inside containers;
- the number of concurrent Airflow tasks and kernels;
- the physical, virtual, cluster, or cloud hosts used;
- internal or public use of generated analysis artifacts;
- redistribution, if an engine-containing image would leave the organization;
- disaster recovery, node replacement, and autoscaling behavior.

This document is an engineering assessment, not legal advice. The controlling
license agreement and Wolfram's written confirmation take precedence.

## Activation choices

The official Wolfram Engine container documents two broad approaches:

| Mode | Pilot suitability | Production concern |
|---|---|---|
| Node-locked activation | Acceptable for one stable local development host | Device binding and ephemeral/container scheduling make rotation and scaling difficult |
| On-demand entitlement | Useful for controlled experiments and elastic execution | Requires entitlement handling, network/service availability, metered cost, and compatible production terms |
| Commercial site/cluster/cloud agreement | Not needed for the documentation phase | Preferred direction when deployment shape and concurrency are known |

Do not automate login with a personal Wolfram password. Persist only the
license artifact or entitlement mechanism authorized for the deployment, and
deliver it through the runtime secret system.

## Container policy

- Pin the Wolfram Engine image by immutable digest and record both reference and
  digest in the stage manifest.
- Never bake a node-locked password file, Wolfram ID, password, or entitlement
  into an image layer.
- Mount authorized license material read-only at runtime or inject the approved
  entitlement as a secret.
- Do not publish an activated internal image to a registry unless the license
  explicitly permits that distribution model.
- Record `$Version`, `$SystemID`, package hashes, paclet/resource identities,
  and relevant codec/library facts with every result.
- Set CPU and memory limits. Wolfram kernels and media values can consume
  substantial memory, especially when frames are materialized.
- Make task concurrency match the license's permitted kernel concurrency.

## Reproducibility policy

- Use explicit random seeds and localize random state for stochastic work.
- Record the actual selected method when a high-level function chooses one
  automatically.
- Pin or hash downloaded paclets, neural nets, and other resource objects.
- Separate deterministic local analysis from cloud, LLM, and external-service
  operations.
- Run the core reproducibility check with outbound network access disabled.
- Export canonical JSON and portable images; do not require `.nb`, `.mx`, or
  another Wolfram-only format to verify a result.
- Define numeric tolerances per measurement. A matching seed does not guarantee
  bit-for-bit equivalence across engine versions, platforms, parallelism, or
  hardware.

## Operational failure modes

| Risk | Control |
|---|---|
| Interactive activation blocks a worker | Preflight the approved unattended mechanism before accepting work |
| License tied to an ephemeral node | Use an approved deployment license; do not schedule node-locked pilots arbitrarily |
| Secret appears in logs or evidence | Redact environment and activation output; allowlist recorded fields |
| Image tag moves | Pin and record an OCI digest |
| Hidden model or paclet download | Pre-resolve, inventory, pin/hash, and test offline |
| External service changes result | Treat it as a separate, explicitly versioned nondeterministic processor |
| Kernel concurrency exceeds entitlement | Align Airflow pools and task concurrency with licensed limits |
| Long computation survives task cancellation | Configure execution timeout and terminate the kernel process group |
| Notebook succeeds but CLI fails | Require the notebook to call the same tested package as `wolframscript` |
| Wolfram becomes unavailable | Keep ingestion independent and retain a Python promotion path |

## Commercial-readiness checkpoint

The pilot report must include a signed-off operational record containing the
intended environment, concurrency, activation mode, network assumptions,
estimated utilization, artifact audience, and Wolfram licensing response. No
production image or DAG should be merged before that checkpoint is approved.
