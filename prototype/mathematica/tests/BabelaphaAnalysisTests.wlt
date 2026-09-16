validInput = <|
    "schema_version" -> "1.0.0",
    "analysis_id" -> "mathematica-local-media-lab-v1",
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
