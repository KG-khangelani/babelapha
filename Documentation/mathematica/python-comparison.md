# Comparison with Babelapha's Python stack

## Decision lens

This comparison asks whether Mathematica produces enough additional value to
justify a proprietary runtime. Feature parity is not sufficient. The relevant
question is whether the resulting investigation is clearer, faster to author,
or materially more capable while remaining reproducible and operable.

| Concern | Wolfram approach | Python approach | Assessment for Babelapha |
|---|---|---|---|
| Interactive analysis | Mathematica notebooks with symbolic outputs and rich controls | Jupyter with pandas and domain libraries | Wolfram may reduce glue code; Python is easier to share and automate |
| Tabular/statistical work | Integrated `Dataset`, statistics, distributions, models | pandas/Polars, SciPy, statsmodels, scikit-learn | Python is the default unless symbolic or cross-domain composition is decisive |
| Audio analysis | First-class `Audio`, signal functions, integrated plots | FFmpeg/ffprobe, librosa, SciPy, torchaudio | Pilot side by side; do not replace FFmpeg |
| Video analysis | First-class `Video`, frame/time mapping, image/ML functions | FFmpeg, OpenCV, PyAV, PyTorch | Wolfram can accelerate exploration; Python has stronger production integration |
| Text/NLP | Built-in text functions, classifiers, semantic and LLM functions | spaCy, transformers, sentence-transformers, dedicated APIs | Compare language accuracy, dependency disclosure, and model control |
| Graph analysis | First-class graph values, algorithms, layouts, symbolic properties | NetworkX/igraph/graph-tool plus visualization libraries | Wolfram is attractive for exploratory graph work; Python avoids new licensing |
| Symbolic computation | Core language strength | SymPy and specialist packages | Wolfram has a meaningful advantage for exact/symbolic workloads |
| Headless execution | `wolframscript` and Wolfram Engine | Standard Python CLI/module/container | Both work; Python is operationally simpler in the existing stack |
| Dependency management | Engine version plus paclets/resources and license | Python lock/constraints plus model artifacts | Wolfram has fewer visible packages but hidden resource/service dependencies need explicit capture |
| Container footprint | Official Engine image; activation required | Existing Airflow image and ordinary OCI workflow | Python wins on current operational fit |
| Licensing | Proprietary; free engine limited to development/prototyping | Mostly open-source libraries with model-specific licenses | Python wins unless Wolfram's value clears the commercial gate |
| Hiring and maintenance | Specialized Wolfram knowledge | Existing project language and broad ecosystem | Python wins for long-lived routine stages |
| Portable outputs | JSON, CSV, PNG, SVG are available | Same | Tie if Wolfram expressions and notebooks are not the only result |

## Baseline implementations for the pilot

The comparison should use equivalent intent, not artificially weak Python:

- media and stream facts: `ffprobe`;
- audio decoding and extraction: FFmpeg;
- numeric arrays and summary metrics: NumPy/SciPy;
- signal and speech-oriented features: librosa where appropriate;
- tables and JSON shaping: Python standard library or pandas;
- plots: Matplotlib;
- provenance graph experiment: NetworkX;
- tests and schema checks: the existing Python test and contract tooling.

Both implementations must consume the same immutable input bytes and emit the
same canonical field definitions. Visuals may differ, but their underlying
measurements must be comparable.

## Scorecard

Score each dimension from 1 (poor) to 5 (strong), attach evidence, and do not
average away a failed gate.

| Dimension | Weight | Evidence |
|---|---:|---|
| Analytical expressiveness | 20% | code review and supported findings |
| Time to a reviewable analysis | 15% | recorded implementation time and code size |
| Reproducibility | 20% | repeat-run and notebook/headless comparison |
| Provenance completeness | Gate | independently verified evidence bundle |
| Runtime and peak memory | 10% | cold and warm measurements on the same host |
| Operational complexity | 15% | image, activation, dependencies, and failure recovery |
| Maintainability | 10% | testability, readability, skill concentration |
| Licensing and lock-in | 10% | approved use and migration feasibility |
| Portable outputs | Gate | JSON and image inspection without Mathematica |

Wolfram should be recommended for automation only if:

- both gates pass;
- its weighted score exceeds Python's;
- it scores at least one full point higher in analytical expressiveness or
  time to a reviewable analysis;
- no runtime measurement is more than twice the Python baseline without a
  documented analytical benefit that the maintainers explicitly accept; and
- commercial licensing and unattended activation are approved.

## Exit paths

- **Research-only:** retain notebooks and Wolfram packages outside required
  production execution.
- **Selective production:** operate a separately scheduled Wolfram analysis
  DAG with portable artifacts and complete provenance.
- **Python promotion:** use the Wolfram notebook to discover the method, then
  implement the stable production calculation in Python.
- **Reject:** stop if licensing, activation, reproducibility, or portability
  cannot meet the gates.

