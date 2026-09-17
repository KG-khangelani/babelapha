# Mathematica notebook sections

`prototype/mathematica/BabelaphaAnalysis.nb` is the canonical implementation.
The local runner evaluates its tagged input cells directly. The generated
`output/analysis-notebook.nb` carries those complete runnable cells, the
embedded tests, measured results, graphics, and native controls in one
document. There is no hidden analysis package or second calculation path.
The v2 result gate requires source markers, named analytical sections,
embedded graphics, native dynamic controls, an executable initialization cell,
truthful transcript status/method markers, and `Default.nb` styling.

```mermaid
flowchart LR
    I[Verified input and canonical notebook] --> A[Evaluate tagged notebook cells]
    A --> M[Portable measurements]
    A --> V[Embedded visuals and local media]
    A --> C[Visible executable source and tests]
    M --> N[Interactive code-bearing notebook]
    V --> N
    C --> N
    N --> G[Python hash and structure gate]
```

The complete executable source block comes first. It contains stage-labelled
input cells for integrity, evidence, video, colour, motion, sound,
transcription, media intelligence, presentation, export, orchestration, and
the embedded verification tests. The analytical sections are:

1. **Executive overview** — six KPI cards for duration, sampled frames, audio,
   loudness, audible share, and transcript status.
2. **What this run shows** — deterministic observations and limitations with
   the exact result paths that support every statement.
3. **Linked media explorer** — one animated/clickable media-time cursor driving
   the nearest sampled frame and audio measurement plus the active RMS activity
   region, speech text, visual scene, and nearest cross-modal event. The native
   local-video player is loaded on demand and is explicitly independent of the
   analytical cursor because its saved control has no stable seek binding.
4. **Source and runtime** — source, object/run identity, Wolfram runtime,
   canonical notebook hash, network mode, and analysis parameters.
5. **Video storyboard** — the full static contact sheet and Wolfram video
   summary; interactive playback and frame inspection live in the linked
   explorer instead of a second disconnected widget.
6. **Color analysis** — dominant palette, RGB and brightness trajectories,
   saturation, contrast, and colorfulness measurements.
7. **Motion and temporal structure** — adjacent-frame motion,
   color-histogram distance, and thresholded scene-change candidates.
8. **Sound intelligence** — waveform, RMS/peak/loudness curves, spectral
   centroid and spread, zero-crossing rate, pitch candidates, spectrogram,
   audible/silent intervals, and the numeric details behind the linked selector.
9. **Transcript and speech text** — the exact emitted status, method, reason,
   model/sidecar source, statistics, content, timestamped source segments, and
   clearly labelled estimated sentence-navigation timing.
10. **Cross-modal timeline** — brightness, motion, audio activity, RMS,
    loudness, scene markers, and transcript coverage on the same media-time axis
    used by the linked cursor.
11. **Provenance and evidence** — source/evidence/notebook identity, ordered
   evidence-event summary, and the output inventory.
12. **Capabilities and methodology** — `USED`, `UNAVAILABLE`, or
    `NOT_APPLICABLE` status with reasons, followed by method and limitation
    notes.
13. **Re-run the verified notebook** — an input cell that calls the visible
    notebook entry point with the same analysis input used by the launcher.

`Output inventory` is a subsection of provenance in the notebook expression
and is also a required marker at the validation boundary. Empty transcript or
audio lanes remain visible and explain why data is unavailable; they are not
silently converted to zero-valued observations.

The notebook uses Mathematica's standard `Default.nb` styles. Every source cell
uses normal executable `Input` or `Code` style, and the source cells are the
ones imported by the local test and analysis launchers. The explorer is
one self-contained `DynamicModule` with a slider, animator, timeline click
handler, event/scene jump selector, audio-metric selector, numeric time input,
and transcript search. The video player deliberately references the local file under
`ingest/`, so moving or deleting that source breaks playback without changing
the hash-bound analytical result.
