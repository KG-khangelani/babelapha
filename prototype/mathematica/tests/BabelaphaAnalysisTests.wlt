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
