validInput = <|
    "schema_version" -> "2.0.0",
    "analysis_id" -> "mathematica-local-media-lab-v2",
    "object_id" -> "local-sample-0123456789ab",
    "run_id" -> "local-0123456789abcdef",
    "package_sha256" -> BabelaphaAnalysis`PackageSourceHash[],
    "source" -> <|
        "path" -> "ingest/sample.mp4",
        "filename" -> "sample.mp4",
        "sha256" -> StringRepeat["a", 64],
        "size_bytes" -> 1024,
        "media_type" -> "video/mp4"
    |>,
    "transcript" -> <|
        "mode" -> "prefer_sidecar",
        "sidecar" -> Null
    |>,
    "evidence" -> <|
        "path" -> "artefacts/source-evidence.json",
        "sha256" -> StringRepeat["b", 64]
    |>,
    "output_directory" -> "output",
    "parameters" -> <|
        "silence_threshold_db" -> -40.,
        "frame_seconds" -> .04,
        "hop_seconds" -> .02,
        "random_seed" -> 20260916
    |>
|>;

VerificationTest[
    AssociationQ[BabelaphaAnalysis`ValidateAnalysisInput[validInput]],
    True,
    TestID -> "valid-input-is-accepted"
]

VerificationTest[
    FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[Append[validInput, "unknown" -> True]]],
    True,
    TestID -> "unknown-top-level-field-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["source", "path"] = "../outside.mp4";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "path-traversal-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["parameters", "frame_seconds"] = 0.;
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "zero-frame-duration-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["parameters", "hop_seconds"] = .05;
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "hop-longer-than-frame-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["source", "path"] = "other/sample.mp4";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "source-outside-ingest-is-rejected"
]

VerificationTest[
    StringMatchQ[BabelaphaAnalysis`PackageSourceHash[], RegularExpression["^[a-f0-9]{64}$"]],
    True,
    TestID -> "package-source-hash-is-sha256"
]

VerificationTest[
    BabelaphaAnalysis`FailureExitCode[
        BabelaphaAnalysis`ValidateAnalysisInput[Append[validInput, "unknown" -> True]]
    ],
    10,
    TestID -> "typed-input-failure-has-stable-exit-code"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["transcript", "mode"] = "cloud";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "unsupported-transcript-mode-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["transcript", "mode"] = "sidecar";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "sidecar-mode-requires-sidecar"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["object_id"] = "x";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "noncanonical-object-id-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["run_id"] = "y";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "noncanonical-run-id-is-rejected"
]

VerificationTest[
    Module[{invalid = validInput},
        invalid["source", "path"] = "ingest/nested/sample.mp4";
        FailureQ[BabelaphaAnalysis`ValidateAnalysisInput[invalid]]
    ],
    True,
    TestID -> "nested-ingest-source-is-rejected"
]

VerificationTest[
    Module[{path, result},
        path = FileNameJoin[{$TemporaryDirectory, "babelapha-out-of-range.srt"}];
        Export[path, "1\n00:00:12,000 --> 00:00:15,000\nToo late.\n", "Text"];
        result = BabelaphaAnalysis`PackageScope`analyzeTranscriptSidecar[path, 10.];
        DeleteFile[path];
        Lookup[result, "status", ""]
    ],
    "UNAVAILABLE",
    TestID -> "out-of-range-sidecar-cue-is-unavailable"
]

intelligenceFixture = <|
    "duration_seconds" -> 4.,
    "video_analytics" -> <|
        "per_frame" -> {
            <|"time_seconds" -> 0., "frame_difference" -> 0., "brightness" -> .4, "colorfulness" -> .1, "mean_color_hex" -> "#445566"|>,
            <|"time_seconds" -> 2., "frame_difference" -> .3, "brightness" -> .6, "colorfulness" -> .2, "mean_color_hex" -> "#667788"|>,
            <|"time_seconds" -> 4., "frame_difference" -> .1, "brightness" -> .5, "colorfulness" -> .15, "mean_color_hex" -> "#556677"|>
        },
        "scene_changes" -> <|
            "candidates" -> {
                <|"time_seconds" -> 2., "score" -> .7|>
            }
        |>
    |>,
    "audio_analysis" -> <|
        "available" -> True,
        "rms_series" -> TimeSeries[{.01, .10, .05}, {{0., 2., 4.}}],
        "summary" -> <|
            "audio_duration_seconds" -> 4.,
            "audible_intervals_seconds" -> {{.5, 1.5}, {1.6, 3.5}}
        |>
    |>,
    "transcript" -> <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "text" -> "First sentence. Second sentence.",
        "segments" -> {
            <|"start_seconds" -> 0., "end_seconds" -> 4., "text" -> "First sentence. Second sentence."|>
        },
        "statistics" -> <|"word_count" -> 4|>
    |>
|>;

derivedIntelligence = BabelaphaAnalysis`PackageScope`deriveMediaIntelligence[
    intelligenceFixture,
    <|"silence_threshold_db" -> -40.|>
];

VerificationTest[
    Sort[Keys[derivedIntelligence]],
    Sort[{"audio_activity", "speech_segments", "scene_segments", "cross_modal", "insights"}],
    TestID -> "media-intelligence-contract-is-complete"
]

VerificationTest[
    {
        derivedIntelligence["audio_activity", "regions"][[1, "interval_count"]],
        derivedIntelligence["speech_segments", "segment_count"],
        derivedIntelligence["speech_segments", "timing_basis"]
    },
    {2, 2, "MIXED_WITH_ESTIMATED_SENTENCE_TIMING"},
    TestID -> "activity-and-speech-navigation-are-segmented"
]

VerificationTest[
    {
        derivedIntelligence["scene_segments", "boundary_count"],
        Length[derivedIntelligence["scene_segments", "segments"]],
        derivedIntelligence["cross_modal", "sample_count"],
        Length[derivedIntelligence["cross_modal", "events"]]
    },
    {1, 2, 3, 2},
    TestID -> "scene-and-cross-modal-events-are-derived"
]

VerificationTest[
    Module[{audio, chunks},
        audio = Audio[ConstantArray[0., 8000], SampleRate -> 8000];
        chunks = BabelaphaAnalysis`PackageScope`transcriptAudioChunks[audio, 1., 30.];
        ListQ[chunks] && Length[chunks] == 1 && SameQ[First[chunks], audio]
    ],
    True,
    TestID -> "short-transcript-audio-does-not-require-padding"
]

VerificationTest[
    BabelaphaAnalysis`PackageScope`transcriptEffectiveDuration[10.0266666667, 10.006],
    10.006,
    SameTest -> (Abs[#1 - #2] < 10.^-9 &),
    TestID -> "transcript-duration-is-bounded-by-canonical-media-duration"
]
