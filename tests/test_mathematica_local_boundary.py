import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "prototype" / "mathematica" / "local_boundary.py"
SPEC = importlib.util.spec_from_file_location("mathematica_local_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(boundary)

import jsonschema


class MathematicaLocalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "Local-prototype"
        boundary.initialize_workspace(self.workspace)
        self.source_path = self.workspace / "ingest" / "sample.mp4"
        self.source_path.write_bytes(b"deterministic-video-fixture\x00\x01\x02")
        boundary.prepare_analysis_input(self.workspace)
        self._write_runtime_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def _input(self):
        return boundary.load_json(self.workspace / "artefacts" / "analysis-input.json")

    def _write_runtime_manifest(
        self,
        *,
        wolfram_version="15.0.1 for Microsoft Windows (64-bit)",
        system_id="Windows-x86-64",
        version_number=15.0,
    ):
        analysis_input = self._input()
        runtime = {
            "schema_version": boundary.SCHEMA_VERSION,
            "recorded_at": "2026-09-16T00:00:00Z",
            "local_only": True,
            "workspace": str(self.workspace.resolve()),
            "source_path": str(self.source_path.resolve()),
            "analysis_id": analysis_input["analysis_id"],
            "run_id": analysis_input["run_id"],
            "package_sha256": analysis_input["package_sha256"],
            "git_commit": "0" * 40,
            "git_worktree_clean": True,
            "git_status_entry_count": 0,
            "wolfram": {
                "wolframscript_path": "C:/Wolfram/wolframscript.exe",
                "kernel_path": "C:/Wolfram/WolframKernel.exe",
                "version": wolfram_version,
                "version_number": version_number,
                "release_number": 1,
                "system_id": system_id,
                "processor_type": "x86-64",
                "media_backend": "Wolfram Language Import",
            },
            "python": {
                "executable": "python",
                "role": "input and output contract boundary only",
            },
            "analysis_parameters": {
                **analysis_input["parameters"],
                "transcript_mode": analysis_input["transcript"]["mode"],
            },
            "speech_model_cache_requested": False,
            "repeatability_requested": False,
        }
        path = self.workspace / "artefacts" / "runtime.json"
        path.write_text(json.dumps(runtime), encoding="utf-8")
        return path

    def _write_outputs(self):
        outputs = []
        for name, media_type in sorted(boundary.EXPECTED_OUTPUT_MEDIA_TYPES.items()):
            path = self.workspace / "output" / name
            if name == "analysis-notebook.nb":
                sections = [
                    "Executive overview",
                    "What this run shows",
                    "Linked media explorer",
                    "Video storyboard",
                    "Color analysis",
                    "Motion and temporal structure",
                    "Sound intelligence",
                    "Transcript and speech text",
                    "Cross-modal timeline",
                    "Provenance and evidence",
                    "Output inventory",
                    "Capabilities and methodology",
                    "Re-run through the verified package",
                ]
                body = (
                    "Notebook[{\n"
                    + "\n".join(sections)
                    + "\n"
                    + "GraphicsBox[{}]\n" * 5
                    + "DynamicModuleBox[{}]\n"
                    + "SliderBox[{}]\n"
                    + "PopupMenuBox[{}]\n" * 2
                    + "AnimatorBox[{}]\n"
                    + "InputFieldBox[{}]\n"
                    + 'ButtonBox["Load local video"]\n'
                    + "Shared media time\n"
                    + "Nearest frame time\n"
                    + "InitializationCell -> True\n"
                    + 'StyleDefinitions -> "Default.nb"\n'
                    + "UNAVAILABLE\n"
                    + "wolfram_whisper_v1_tiny\n"
                    + "}]\n"
                ).encode("utf-8")
            elif name.endswith(".png"):
                body = (
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                    + struct.pack(">II", 1, 1)
                    + b"test-png"
                )
            elif name.endswith(".svg"):
                body = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>\n'
            elif name.endswith(".html"):
                body = b"<!doctype html><html><head></head><body>report</body></html>\n"
            elif name.endswith(".md"):
                body = b"# Portable Mathematica report\n"
            else:
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

    @staticmethod
    def _distribution(value=1.0, count=1):
        if count == 0:
            return {
                "count": 0,
                "minimum": None,
                "q05": None,
                "q25": None,
                "median": None,
                "q75": None,
                "q95": None,
                "maximum": None,
                "mean": None,
                "standard_deviation": None,
            }
        return {
            "count": count,
            "minimum": value,
            "q05": value,
            "q25": value,
            "median": value,
            "q75": value,
            "q95": value,
            "maximum": value,
            "mean": value,
            "standard_deviation": 0.0,
        }

    def _audio_analytics(self, audio=True):
        feature_names = (
            "rms_amplitude",
            "peak_amplitude",
            "spectral_centroid",
            "spectral_spread",
            "zero_crossing_rate",
            "local_loudness",
            "fundamental_frequency",
        )
        if not audio:
            return {
                "status": "UNAVAILABLE",
                "reason": "The video has no decodable audio track.",
                "method": "Wolfram AudioLocalMeasurements over configured overlapping windows",
                "dynamics": {},
                "distribution": {},
                "frequency": {},
                "pitch": {
                    "status": "UNAVAILABLE",
                    "reason": "The video has no decodable audio track.",
                    "method": "AudioLocalMeasurements/FundamentalFrequency",
                    "observation_count": 0,
                    "window_count": 0,
                    "coverage_fraction": 0.0,
                    "fundamental_frequency_hz": self._distribution(count=0),
                },
                "availability": {
                    name: {
                        "status": "UNAVAILABLE",
                        "observation_count": 0,
                        "reason": "No audio track.",
                    }
                    for name in feature_names
                },
            }
        return {
            "status": "AVAILABLE",
            "reason": "",
            "method": "Wolfram AudioLocalMeasurements over configured overlapping windows",
            "dynamics": {
                "rms_amplitude": self._distribution(0.1, 10),
                "peak_amplitude": self._distribution(0.5, 10),
                "rms_dbfs": self._distribution(-20.0, 10),
                "local_loudness": self._distribution(-18.5, 10),
                "crest_factor": 5.0,
                "crest_factor_db": 13.9794,
                "local_dynamic_range_db": 4.0,
            },
            "distribution": {
                "rms_amplitude_histogram": {
                    "bin_edges": [0.0, 0.2],
                    "counts": [10],
                    "fractions": [1.0],
                },
                "rms_dbfs_histogram": {
                    "bin_edges": [-30.0, -10.0],
                    "counts": [10],
                    "fractions": [1.0],
                },
            },
            "frequency": {
                "spectral_centroid_hz": self._distribution(440.0, 10),
                "spectral_spread_hz": self._distribution(200.0, 10),
                "zero_crossing_rate": self._distribution(100.0, 10),
                "nyquist_frequency_hz": 24000.0,
            },
            "pitch": {
                "status": "AVAILABLE",
                "reason": "",
                "method": "AudioLocalMeasurements/FundamentalFrequency",
                "observation_count": 5,
                "window_count": 10,
                "coverage_fraction": 0.5,
                "fundamental_frequency_hz": self._distribution(200.0, 5),
            },
            "availability": {
                name: {
                    "status": "AVAILABLE",
                    "observation_count": 5 if name == "fundamental_frequency" else 10,
                    "reason": "",
                }
                for name in feature_names
            },
        }

    def _video_analytics(self):
        times = [0.0, 2.0, 4.0]
        frames = []
        for index, timestamp in enumerate(times, start=1):
            frames.append(
                {
                    "sample_index": index,
                    "time_seconds": timestamp,
                    "frame_difference": 0.0 if index == 1 else 0.1,
                    "color_histogram_distance": 0.0 if index == 1 else 0.1,
                    "brightness": 0.4,
                    "saturation": 0.2,
                    "contrast": 0.1,
                    "colorfulness": 0.15,
                    "mean_rgb": {"red": 0.3, "green": 0.4, "blue": 0.5},
                    "mean_color_hex": "#4C6680",
                }
            )
        return {
            "sample_times_seconds": times,
            "per_frame": frames,
            "color": {
                "method": "deterministic sampled-frame quantization",
                "mean_rgb": {"red": 0.3, "green": 0.4, "blue": 0.5},
                "palette": [
                    {
                        "rank": 1,
                        "hex": "#4C6680",
                        "rgb": {"red": 0.3, "green": 0.4, "blue": 0.5},
                        "fraction": 1.0,
                    }
                ],
                "brightness": self._distribution(0.4, 3),
                "saturation": self._distribution(0.2, 3),
                "contrast": self._distribution(0.1, 3),
                "colorfulness": self._distribution(0.15, 3),
            },
            "scene_changes": {
                "method": "sampled-frame grayscale motion and RGB histogram distance",
                "threshold": 0.2,
                "candidates": [],
            },
        }

    @staticmethod
    def _unavailable_transcript():
        return {
            "status": "UNAVAILABLE",
            "reason": "The pinned local model is not cached.",
            "method": "wolfram_whisper_v1_tiny",
            "text": "",
            "segments": [],
            "statistics": {
                "character_count": 0,
                "word_count": 0,
                "sentence_count": 0,
                "unique_word_count": 0,
                "lexical_diversity": None,
                "words_per_minute": None,
                "top_terms": [],
            },
            "model": None,
            "sidecar": None,
            "inference": None,
        }

    def _media_intelligence(self, *, audio=True):
        audio_activity = (
            {
                "status": "AVAILABLE",
                "reason": "",
                "method": "RMS-threshold intervals merged across short gaps; activity is not speaker diarization",
                "threshold_dbfs": -40.0,
                "merge_gap_seconds": 0.2,
                "minimum_region_seconds": 0.2,
                "audible_coverage_fraction": 0.25,
                "regions": [
                    {
                        "region_index": 1,
                        "start_seconds": 1.0,
                        "end_seconds": 2.0,
                        "active_duration_seconds": 1.0,
                        "interval_count": 1,
                        "duration_seconds": 1.0,
                        "activity_fraction": 1.0,
                    }
                ],
            }
            if audio
            else {
                "status": "UNAVAILABLE",
                "reason": "No decodable audio track was available for activity segmentation.",
                "method": "RMS-threshold intervals merged across short gaps; activity is not speaker diarization",
                "threshold_dbfs": -40.0,
                "merge_gap_seconds": 0.2,
                "minimum_region_seconds": 0.2,
                "audible_coverage_fraction": None,
                "regions": [],
            }
        )
        scene_segments = {
            "status": "AVAILABLE",
            "reason": "",
            "method": "contiguous scenes bounded by consolidated visual-change candidates",
            "minimum_separation_seconds": 0.5,
            "boundary_count": 0,
            "segments": [
                {
                    "scene_index": 1,
                    "start_seconds": 0.0,
                    "end_seconds": 4.0,
                    "duration_seconds": 4.0,
                    "sample_count": 3,
                    "representative_time_seconds": 2.0,
                    "mean_brightness": 0.4,
                    "mean_motion": 0.06666666666666667,
                    "mean_colorfulness": 0.15,
                    "representative_color_hex": "#4C6680",
                    "entry_boundary_score": None,
                }
            ],
        }
        cross_modal = (
            {
                "status": "AVAILABLE",
                "reason": "",
                "method": "nearest-time alignment of video motion and audio RMS; descriptive only",
                "sample_count": 3,
                "motion_rms_pearson_correlation": None,
                "aligned_samples": [
                    {
                        "time_seconds": 0.0,
                        "motion": 0.0,
                        "rms_amplitude": 0.01,
                        "motion_normalized": 0.0,
                        "rms_normalized": 0.0,
                    },
                    {
                        "time_seconds": 2.0,
                        "motion": 0.1,
                        "rms_amplitude": 0.1,
                        "motion_normalized": 1.0,
                        "rms_normalized": 1.0,
                    },
                    {
                        "time_seconds": 4.0,
                        "motion": 0.1,
                        "rms_amplitude": 0.05,
                        "motion_normalized": 1.0,
                        "rms_normalized": 0.4444444444444445,
                    },
                ],
                "events": [
                    {
                        "event_index": 1,
                        "event_type": "AUDIO_VISUAL_PEAK",
                        "time_seconds": 2.0,
                        "window_seconds": [1.75, 2.25],
                        "score": 1.0,
                        "scene_score": None,
                        "motion": 0.1,
                        "rms_amplitude": 0.1,
                        "motion_normalized": 1.0,
                        "rms_normalized": 1.0,
                        "audio_activity": True,
                        "transcript_text": None,
                        "evidence_paths": [
                            "measurements.cross_modal.aligned_samples"
                        ],
                    }
                ],
            }
            if audio
            else {
                "status": "UNAVAILABLE",
                "reason": "Cross-modal alignment requires timestamped video samples and a decodable audio RMS series.",
                "method": "nearest-time alignment of video motion and audio RMS; descriptive only",
                "sample_count": 0,
                "motion_rms_pearson_correlation": None,
                "aligned_samples": [],
                "events": [],
            }
        )
        return {
            "audio_activity": audio_activity,
            "speech_segments": {
                "status": "UNAVAILABLE",
                "reason": "The pinned local model is not cached.",
                "method": "sentence navigation derived from verified transcript segments",
                "timing_basis": "UNAVAILABLE",
                "speaker_diarization": "NOT_PERFORMED",
                "segment_count": 0,
                "segments": [],
            },
            "scene_segments": scene_segments,
            "cross_modal": cross_modal,
            "insights": {
                "method": "deterministic descriptive rules over emitted measurements",
                "items": [
                    {
                        "insight_id": "insight-01",
                        "kind": "OBSERVATION",
                        "headline": "Visual structure",
                        "statement": "One contiguous visual scene covers the source.",
                        "time_seconds": None,
                        "evidence_paths": [
                            "measurements.scene_segments.segments"
                        ],
                    }
                ],
            },
        }

    def _valid_result(self, *, audio=True):
        analysis_input = self._input()
        capabilities = {
            name: {"status": "USED", "reason": ""}
            for name in boundary.CAPABILITY_KEYS
        }
        capabilities["transcript_analysis"] = {
            "status": "UNAVAILABLE",
            "reason": "The pinned local model is not cached.",
        }
        if not audio:
            capabilities["audio_track"] = {
                "status": "UNAVAILABLE",
                "reason": "The source has no audio track.",
            }
            capabilities["sound_analysis"] = {
                "status": "UNAVAILABLE",
                "reason": "The source has no audio track.",
            }
            capabilities["cross_modal_analysis"] = {
                "status": "UNAVAILABLE",
                "reason": "Cross-modal alignment requires timestamped video samples and a decodable audio RMS series.",
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
            "transcript": analysis_input["transcript"],
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
                "video_analytics": self._video_analytics(),
                "audio_analytics": self._audio_analytics(audio),
                "transcript": self._unavailable_transcript(),
                **self._media_intelligence(audio=audio),
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

    def test_prepare_binds_an_optional_transcript_sidecar(self):
        sidecar = self.workspace / "transcripts" / "sample.srt"
        sidecar.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nLocal transcript.\n",
            encoding="utf-8",
        )

        details = boundary.prepare_analysis_input(
            self.workspace, transcript_mode="prefer_sidecar"
        )
        analysis_input = self._input()
        evidence = boundary.load_json(
            self.workspace / "artefacts" / "source-evidence.json"
        )

        self.assertEqual(analysis_input["transcript"]["sidecar"]["format"], "srt")
        self.assertEqual(
            analysis_input["transcript"]["sidecar"]["sha256"],
            hashlib.sha256(sidecar.read_bytes()).hexdigest(),
        )
        self.assertEqual(details["transcript_sha256"], analysis_input["transcript"]["sidecar"]["sha256"])
        self.assertEqual(len(evidence["events"]), 4)
        self.assertEqual(evidence["events"][-1]["artifact_count"], 2)
        self.assertEqual(boundary.validate_analysis_input(self.workspace), analysis_input)

    def test_prepare_enforces_transcript_modes(self):
        with self.assertRaisesRegex(boundary.InputContractError, "requires one"):
            boundary.prepare_analysis_input(self.workspace, transcript_mode="sidecar")

        (self.workspace / "transcripts" / "sample.txt").write_text(
            "Local transcript.", encoding="utf-8"
        )
        with self.assertRaisesRegex(boundary.InputContractError, "requires transcripts/"):
            boundary.prepare_analysis_input(self.workspace, transcript_mode="disabled")

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

    def test_validate_rejects_invalid_pitch_and_transcript_provenance(self):
        invalid_pitch = self._valid_result()
        invalid_pitch["measurements"]["audio_analytics"]["pitch"]["status"] = "BANANA"
        self._write_raw_result(invalid_pitch)
        with self.assertRaisesRegex(boundary.ResultContractError, "pitch.status"):
            boundary.validate_result(self.workspace)

        invented_transcript = self._valid_result()
        invented_transcript["measurements"]["transcript"].update(
            {
                "status": "AVAILABLE",
                "reason": "",
                "method": "unknown_remote_service",
                "text": "Invented transcript",
            }
        )
        invented_transcript["measurements"]["transcript"]["statistics"][
            "character_count"
        ] = len("Invented transcript")
        invented_transcript["capabilities"]["transcript_analysis"] = {
            "status": "USED",
            "reason": "",
        }
        self._write_raw_result(invented_transcript)
        with self.assertRaisesRegex(boundary.ResultContractError, "method is unsupported"):
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
        self._write_runtime_manifest(
            wolfram_version="16.0.0 for Microsoft Windows (64-bit)",
            version_number=16.0,
        )
        self._write_raw_result(result)

        boundary.validate_result(self.workspace)

    def test_validate_rejects_runtime_identity_mismatch(self):
        result = self._valid_result()
        result["processor"]["system_id"] = "made-up-system"
        self._write_raw_result(result)

        with self.assertRaisesRegex(boundary.IntegrityError, "system ID differs"):
            boundary.validate_result(self.workspace)

    def test_audio_intervals_use_audio_stream_duration(self):
        result = self._valid_result()
        result["measurements"]["audio_duration_seconds"] = 4.1
        result["measurements"]["silence_intervals_seconds"][-1][1] = 4.1
        result["measurements"]["audio_activity"][
            "audible_coverage_fraction"
        ] = 1.0 / 4.1
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

    def test_validate_rejects_spoofed_output_format(self):
        result = self._valid_result()
        png = self.workspace / "output" / "video-summary.png"
        fake = b"plain text posing as a png"
        png.write_bytes(fake)
        record = next(item for item in result["outputs"] if item["path"] == png.name)
        record["sha256"] = hashlib.sha256(fake).hexdigest()
        record["size_bytes"] = len(fake)
        self._write_raw_result(result)

        with self.assertRaisesRegex(boundary.ResultContractError, "not a PNG"):
            boundary.validate_result(self.workspace)

    def test_validate_rejects_a_static_or_custom_styled_notebook(self):
        cases = (
            (b"DynamicModuleBox[", b"StaticModuleBox[", "linked native"),
            (b'StyleDefinitions -> "Default.nb"', b'StyleDefinitions -> "Custom.nb"', "default notebook styles"),
            (b"wolfram_whisper_v1_tiny", b"missing_transcript_method", "actual transcript method"),
        )
        for old, new, message in cases:
            with self.subTest(message=message):
                result = self._valid_result()
                notebook = self.workspace / "output" / "analysis-notebook.nb"
                body = notebook.read_bytes().replace(old, new)
                notebook.write_bytes(body)
                record = next(
                    item for item in result["outputs"] if item["path"] == notebook.name
                )
                record["sha256"] = hashlib.sha256(body).hexdigest()
                record["size_bytes"] = len(body)
                self._write_raw_result(result)
                with self.assertRaisesRegex(boundary.ResultContractError, message):
                    boundary.validate_result(self.workspace)

    def test_failed_revalidation_removes_stale_success_markers(self):
        result = self._valid_result()
        self._write_raw_result(result)
        boundary.validate_result(self.workspace)
        repeatability = self.workspace / "artefacts" / "repeatability.json"
        repeatability.write_text("stale", encoding="utf-8")

        (self.workspace / "output" / "report.md").write_text(
            "tampered", encoding="utf-8"
        )
        with self.assertRaises(boundary.IntegrityError):
            boundary.validate_result(self.workspace)

        self.assertFalse((self.workspace / "output" / "result.json").exists())
        self.assertFalse(repeatability.exists())

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

    def test_documents_conform_to_published_schemas(self):
        analysis_input = self._input()
        evidence = boundary.load_json(self.workspace / "artefacts" / "source-evidence.json")
        result = self._valid_result()
        documents = [
            ("mathematica-local-analysis-input-v2.schema.json", analysis_input),
            ("mathematica-local-source-evidence-v2.schema.json", evidence),
            ("mathematica-local-analysis-result-v2.schema.json", result),
        ]
        for filename, document in documents:
            with self.subTest(schema=filename):
                schema = json.loads((ROOT / "contracts" / filename).read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator(schema).validate(document)

        invalid_result = copy.deepcopy(result)
        invalid_result["measurements"]["transcript"]["model"] = {}
        result_schema = json.loads(
            (ROOT / "contracts" / "mathematica-local-analysis-result-v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(result_schema).validate(invalid_result)


if __name__ == "__main__":
    unittest.main()
