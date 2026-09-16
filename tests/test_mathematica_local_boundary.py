import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "prototype" / "mathematica" / "local_boundary.py"
SPEC = importlib.util.spec_from_file_location("mathematica_local_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(boundary)

try:
    import jsonschema
except ImportError:  # pragma: no cover - the boundary itself is dependency-free
    jsonschema = None


class MathematicaLocalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "Local-prototype"
        boundary.initialize_workspace(self.workspace)
        self.source_path = self.workspace / "ingest" / "sample.mp4"
        self.source_path.write_bytes(b"deterministic-video-fixture\x00\x01\x02")
        boundary.prepare_analysis_input(self.workspace)

    def tearDown(self):
        self.temporary.cleanup()

    def _input(self):
        return boundary.load_json(self.workspace / "artefacts" / "analysis-input.json")

    def _write_outputs(self):
        outputs = []
        for name, media_type in sorted(boundary.EXPECTED_OUTPUT_MEDIA_TYPES.items()):
            path = self.workspace / "output" / name
            body = f"portable Mathematica artifact: {name}\n".encode("utf-8")
            path.write_bytes(body)
            outputs.append(
                {
                    "path": name,
                    "media_type": media_type,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "size_bytes": len(body),
                }
            )
        return outputs

    def _valid_result(self, *, audio=True):
        analysis_input = self._input()
        capabilities = {
            name: {"status": "USED", "reason": ""}
            for name in boundary.CAPABILITY_KEYS
        }
        if not audio:
            capabilities["audio_track"] = {
                "status": "UNAVAILABLE",
                "reason": "The source has no audio track.",
            }
        return {
            "schema_version": analysis_input["schema_version"],
            "analysis_id": analysis_input["analysis_id"],
            "object_id": analysis_input["object_id"],
            "run_id": analysis_input["run_id"],
            "processor": {
                "name": "BabelaphaAnalysis",
                "wolfram_version": "15.0.1 for Microsoft Windows (64-bit)",
                "system_id": "Windows-x86-64",
                "package_sha256": analysis_input["package_sha256"],
                "network_mode": "disabled",
            },
            "source": analysis_input["source"],
            "evidence": analysis_input["evidence"],
            "parameters": analysis_input["parameters"],
            "capabilities": capabilities,
            "measurements": {
                "duration_seconds": 4.0,
                "audio_duration_seconds": 4.0 if audio else None,
                "sample_rate_hz": 48000 if audio else None,
                "channel_count": 2 if audio else None,
                "rms_amplitude": 0.1 if audio else None,
                "peak_amplitude": 0.5 if audio else None,
                "integrated_loudness_lufs": -18.5 if audio else None,
                "audible_intervals_seconds": [[1.0, 2.0]] if audio else [],
                "silence_intervals_seconds": [[0.0, 1.0], [2.0, 4.0]] if audio else [],
                "spectral_centroid_hz": (
                    {"minimum": 200.0, "mean": 440.0, "maximum": 900.0}
                    if audio
                    else {"minimum": None, "mean": None, "maximum": None}
                ),
                "measurement_series": {
                    "time_count": 10 if audio else 0,
                    "component_names": ["rms_amplitude", "spectral_centroid_hz"] if audio else [],
                },
                "evidence_events": {
                    "event_count": 2,
                    "event_types": ["SOURCE_DISCOVERED", "SOURCE_HASH_VERIFIED"],
                },
                "tabular_summary": {
                    "row_count": 2,
                    "column_names": [
                        "artifact_count",
                        "event_type",
                        "sequence",
                        "stage",
                        "status",
                    ],
                },
                "video": {
                    "duration_seconds": 4.0,
                    "frame_count_sampled": 3,
                    "frame_dimensions": [640, 360],
                    "brightness": {"minimum": 0.1, "mean": 0.4, "maximum": 0.8},
                    "mean_rgb": {"red": 0.3, "green": 0.4, "blue": 0.5},
                    "motion": {
                        "method": "mean-absolute-grayscale-frame-difference",
                        "transition_count": 2,
                        "mean": 0.15,
                        "maximum": 0.25,
                    },
                },
            },
            "provenance_summary": {
                "task_count": 2,
                "artifact_count": 1,
                "integrity_conflict_count": 0,
                "evidence_sha256": analysis_input["evidence"]["sha256"],
            },
            "outputs": self._write_outputs(),
        }

    def _write_raw_result(self, result):
        path = self.workspace / "output" / "result.raw.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        return path

    def test_prepare_writes_repeatable_canonical_identity_and_evidence(self):
        first_input = (self.workspace / "artefacts" / "analysis-input.json").read_bytes()
        first_evidence = (self.workspace / "artefacts" / "source-evidence.json").read_bytes()

        second = boundary.prepare_analysis_input(self.workspace)

        self.assertEqual(
            first_input,
            (self.workspace / "artefacts" / "analysis-input.json").read_bytes(),
        )
        self.assertEqual(
            first_evidence,
            (self.workspace / "artefacts" / "source-evidence.json").read_bytes(),
        )
        self.assertEqual(second["source_sha256"], hashlib.sha256(self.source_path.read_bytes()).hexdigest())
        self.assertEqual(boundary.validate_analysis_input(self.workspace), self._input())

    def test_prepare_invalidates_prior_result_markers(self):
        output = self.workspace / "output"
        (output / "result.json").write_text("old canonical result", encoding="utf-8")
        (output / "result.raw.json").write_text("old raw result", encoding="utf-8")
        repeatability = self.workspace / "artefacts" / "repeatability.json"
        repeatability.write_text("old repeatability record", encoding="utf-8")

        boundary.prepare_analysis_input(self.workspace)

        self.assertFalse((output / "result.json").exists())
        self.assertFalse((output / "result.raw.json").exists())
        self.assertFalse(repeatability.exists())

    def test_prepare_requires_exactly_one_supported_video(self):
        (self.workspace / "ingest" / "second.mov").write_bytes(b"second")
        with self.assertRaisesRegex(boundary.InputContractError, "exactly one"):
            boundary.prepare_analysis_input(self.workspace)

        (self.workspace / "ingest" / "second.mov").unlink()
        self.source_path.rename(self.source_path.with_suffix(".txt"))
        with self.assertRaisesRegex(boundary.InputContractError, "Unsupported ingest"):
            boundary.prepare_analysis_input(self.workspace)

    def test_prepared_input_detects_source_and_evidence_tampering(self):
        self.source_path.write_bytes(self.source_path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(boundary.IntegrityError, "size differs"):
            boundary.validate_analysis_input(self.workspace)

        self.source_path.write_bytes(b"deterministic-video-fixture\x00\x01\x02")
        evidence_path = self.workspace / "artefacts" / "source-evidence.json"
        evidence_path.write_bytes(evidence_path.read_bytes() + b" ")
        with self.assertRaisesRegex(boundary.IntegrityError, "SHA-256 differs"):
            boundary.validate_analysis_input(self.workspace)

    def test_prepared_input_binds_the_current_wolfram_package(self):
        analysis_input = self._input()
        self.assertEqual(
            analysis_input["package_sha256"],
            boundary.package_source_hash(),
        )
        analysis_input["package_sha256"] = "0" * 64
        input_path = self.workspace / "artefacts" / "analysis-input.json"
        input_path.write_bytes(boundary.canonical_json_bytes(analysis_input))

        with self.assertRaisesRegex(boundary.IntegrityError, "package SHA-256 differs"):
            boundary.validate_analysis_input(self.workspace)

    def test_validate_canonicalizes_complete_mathematica_result(self):
        result = self._valid_result()
        self._write_raw_result(result)

        details = boundary.validate_result(self.workspace)

        canonical_path = self.workspace / "output" / "result.json"
        self.assertEqual(canonical_path.read_bytes(), boundary.canonical_json_bytes(result))
        self.assertEqual(details["result_sha256"], hashlib.sha256(canonical_path.read_bytes()).hexdigest())
        self.assertEqual(details["output_count"], 7)

    def test_validate_allows_explicit_no_audio_result(self):
        result = self._valid_result(audio=False)
        self._write_raw_result(result)

        boundary.validate_result(self.workspace)

        self.assertTrue((self.workspace / "output" / "result.json").is_file())

    def test_validate_rejects_measurements_when_audio_is_unavailable(self):
        result = self._valid_result(audio=False)
        result["measurements"]["rms_amplitude"] = 0.1
        self._write_raw_result(result)

        with self.assertRaisesRegex(boundary.ResultContractError, "null audio measurements"):
            boundary.validate_result(self.workspace)

    def test_validate_requires_core_mathematica_capabilities(self):
        result = self._valid_result()
        result["capabilities"]["tabular"] = {
            "status": "UNAVAILABLE",
            "reason": "Tabular could not be constructed.",
        }
        self._write_raw_result(result)

        with self.assertRaisesRegex(boundary.ResultContractError, "core Mathematica"):
            boundary.validate_result(self.workspace)

    def test_validate_accepts_a_newer_wolfram_major_version(self):
        result = self._valid_result()
        result["processor"]["wolfram_version"] = "16.0.0 for Microsoft Windows (64-bit)"
        self._write_raw_result(result)

        boundary.validate_result(self.workspace)

    def test_audio_intervals_use_audio_stream_duration(self):
        result = self._valid_result()
        result["measurements"]["audio_duration_seconds"] = 4.1
        result["measurements"]["silence_intervals_seconds"][-1][1] = 4.1
        self._write_raw_result(result)

        boundary.validate_result(self.workspace)

    def test_validate_rejects_identity_unknown_fields_and_nonfinite_numbers(self):
        cases = []
        mismatched = self._valid_result()
        mismatched["source"]["sha256"] = "0" * 64
        cases.append((mismatched, boundary.IntegrityError, "source differs"))

        unknown = self._valid_result()
        unknown["unexpected"] = True
        cases.append((unknown, boundary.ResultContractError, r"unknown=\['unexpected'\]"))

        nonfinite = self._valid_result()
        nonfinite["measurements"]["rms_amplitude"] = float("nan")
        cases.append((nonfinite, boundary.ResultContractError, "non-finite"))

        for result, error_type, message in cases:
            with self.subTest(message=message):
                self._write_raw_result(result)
                with self.assertRaisesRegex(error_type, message):
                    boundary.validate_result(self.workspace)

    def test_validate_rejects_unsafe_or_tampered_outputs(self):
        unsafe = self._valid_result()
        unsafe["outputs"][0]["path"] = "../analysis-notebook.nb"
        self._write_raw_result(unsafe)
        with self.assertRaisesRegex(boundary.ResultContractError, "direct child"):
            boundary.validate_result(self.workspace)

        tampered = self._valid_result()
        self._write_raw_result(tampered)
        (self.workspace / "output" / "report.md").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(boundary.IntegrityError, "Output size differs"):
            boundary.validate_result(self.workspace)

    def test_strict_loader_rejects_duplicate_keys(self):
        path = self.workspace / "artefacts" / "duplicate.json"
        path.write_text('{"same": 1, "same": 2}', encoding="utf-8")
        with self.assertRaisesRegex(boundary.InputContractError, "duplicate JSON key"):
            boundary.load_json(path)

    def test_test_wav_is_repeatable_but_is_not_accepted_as_ingest_video(self):
        first = Path(self.temporary.name) / "first.wav"
        second = Path(self.temporary.name) / "second.wav"
        first_identity = boundary.write_deterministic_test_wav(first)
        second_identity = boundary.write_deterministic_test_wav(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first_identity, second_identity)

    @unittest.skipIf(jsonschema is None, "jsonschema is not installed")
    def test_documents_conform_to_published_schemas(self):
        analysis_input = self._input()
        evidence = boundary.load_json(self.workspace / "artefacts" / "source-evidence.json")
        result = self._valid_result()
        documents = [
            ("mathematica-local-analysis-input-v1.schema.json", analysis_input),
            ("mathematica-local-source-evidence-v1.schema.json", evidence),
            ("mathematica-local-analysis-result-v1.schema.json", result),
        ]
        for filename, document in documents:
            with self.subTest(schema=filename):
                schema = json.loads((ROOT / "contracts" / filename).read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator(schema).validate(document)


if __name__ == "__main__":
    unittest.main()
