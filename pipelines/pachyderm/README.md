# Pachyderm Pipelines

This folder contains Pachyderm pipeline specifications that complement the
Airflow workflows. The `transcription-postprocess` pipeline ingests raw
transcripts (JSON or text files) written by the Airflow DAG and copies them into
an output repo where downstream analytics jobs can read versioned data.

## Usage

1. Log in to a Pachyderm cluster and port-forward the console if needed.
2. Create the input repo:
   ```bash
   pachctl create repo raw-transcripts
   ```
3. Submit the pipeline:
   ```bash
   pachctl create pipeline -f transcription-pipeline.yaml
   ```
4. Inspect the pipeline logs and commits to ensure data is flowing correctly:
   ```bash
   pachctl list pipeline
   pachctl list commit transcription-postprocess
   ```

Replace the placeholder `alpine` image with an application-specific container as
soon as the real post-processing code is ready.
