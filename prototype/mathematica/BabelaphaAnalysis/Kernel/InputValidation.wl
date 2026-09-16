PackageExported[ValidateAnalysisInput]

PackageScoped[validateAnalysisInput]
PackageScoped[ensureCondition]
PackageScoped[safeRelativePathQ]
PackageScoped[resolveWorkspacePath]
PackageScoped[fileSHA256]
PackageScoped[finiteRealQ]
PackageScoped[$analysisSchemaVersion]
PackageScoped[$analysisID]

$analysisSchemaVersion = "2.0.0";
$analysisID = "mathematica-local-media-lab-v2";

ensureCondition[condition_, tag_Symbol, reason_String, message_String, exitCode_Integer, details_: <||>] :=
    If[! TrueQ[condition], throwAnalysisException[tag, reason, message, exitCode, details]];

finiteRealQ[value_] := MatchQ[value, _Integer | _Real];

sha256StringQ[value_] :=
    StringQ[value] && StringMatchQ[value, RegularExpression["^[a-f0-9]{64}$"]];

safeRelativePathQ[value_] := Module[{normalized, parts},
    If[! StringQ[value] || StringLength[value] == 0, Return[False]];
    If[StringContainsQ[value, "\\"], Return[False]];
    normalized = StringReplace[value, "\\" -> "/"];
    If[StringStartsQ[normalized, "/"] ||
       StringMatchQ[normalized, RegularExpression["^[A-Za-z]:.*"]], Return[False]];
    parts = StringSplit[normalized, "/", All];
    parts =!= {} && AllTrue[parts, StringLength[#] > 0 && ! MemberQ[{".", ".."}, #] &]
];

directChildPathQ[value_, root_String] := Module[{parts},
    If[! safeRelativePathQ[value], Return[False]];
    parts = StringSplit[value, "/", All];
    Length[parts] === 2 && First[parts] === root && StringLength[Last[parts]] > 0
];

resolveWorkspacePath[workspaceRoot_String, relativePath_String] := Module[
    {root, candidate, rootPrefix},
    ensureCondition[
        safeRelativePathQ[relativePath],
        InvalidInputException,
        "UNSAFE_RELATIVE_PATH",
        "A local prototype path must be a safe relative path.",
        10,
        <|"Path" -> relativePath|>
    ];
    root = ExpandFileName[workspaceRoot];
    candidate = ExpandFileName[FileNameJoin[Join[{root}, StringSplit[StringReplace[relativePath, "\\" -> "/"], "/"]]]];
    rootPrefix = If[StringEndsQ[root, $PathnameSeparator], root, root <> $PathnameSeparator];
    ensureCondition[
        StringStartsQ[ToLowerCase[candidate], ToLowerCase[rootPrefix]],
        InvalidInputException,
        "PATH_ESCAPES_WORKSPACE",
        "A local prototype path resolved outside the workspace.",
        10,
        <|"Path" -> relativePath|>
    ];
    candidate
];

fileSHA256[path_String] := IntegerString[FileHash[path, "SHA256"], 16, 64];

validateExactKeys[association_Association, allowed_List, location_String] := Module[{missing, unknown},
    missing = Complement[allowed, Keys[association]];
    unknown = Complement[Keys[association], allowed];
    ensureCondition[
        missing === {} && unknown === {},
        InvalidInputException,
        "INVALID_FIELDS",
        "The analysis input contains missing or unknown fields.",
        10,
        <|"Location" -> location, "Missing" -> missing, "Unknown" -> unknown|>
    ];
];

validateSource[source_] := Module[{allowed},
    ensureCondition[
        AssociationQ[source], InvalidInputException, "INVALID_SOURCE", "source must be an object.", 10
    ];
    allowed = {"path", "filename", "sha256", "size_bytes", "media_type"};
    validateExactKeys[source, allowed, "source"];
    ensureCondition[directChildPathQ[source["path"], "ingest"], InvalidInputException, "INVALID_SOURCE_PATH", "source.path must be one safe direct child of ingest/.", 10];
    ensureCondition[StringQ[source["filename"]] && source["filename"] === FileNameTake[StringReplace[source["path"], "/" -> $PathnameSeparator]], InvalidInputException, "INVALID_SOURCE_FILENAME", "source.filename must match source.path.", 10];
    ensureCondition[sha256StringQ[source["sha256"]], InvalidInputException, "INVALID_SOURCE_HASH", "source.sha256 must be a lowercase SHA-256 digest.", 10];
    ensureCondition[IntegerQ[source["size_bytes"]] && source["size_bytes"] > 0, InvalidInputException, "INVALID_SOURCE_SIZE", "source.size_bytes must be a positive integer.", 10];
    ensureCondition[StringQ[source["media_type"]] && StringStartsQ[source["media_type"], "video/"], InvalidInputException, "UNSUPPORTED_MEDIA_TYPE", "The local Mathematica pilot currently requires a video source.", 10];
];

validateEvidenceReference[evidence_] := Module[{},
    ensureCondition[AssociationQ[evidence], InvalidInputException, "INVALID_EVIDENCE", "evidence must be an object.", 10];
    validateExactKeys[evidence, {"path", "sha256"}, "evidence"];
    ensureCondition[evidence["path"] === "artefacts/source-evidence.json", InvalidInputException, "INVALID_EVIDENCE_PATH", "evidence.path must be artefacts/source-evidence.json.", 10];
    ensureCondition[sha256StringQ[evidence["sha256"]], InvalidInputException, "INVALID_EVIDENCE_HASH", "evidence.sha256 must be a lowercase SHA-256 digest.", 10];
];

validateTranscriptSidecar[Null] := Null;
validateTranscriptSidecar[sidecar_] := Module[{allowed, extension, expected},
    ensureCondition[AssociationQ[sidecar], InvalidInputException, "INVALID_TRANSCRIPT_SIDECAR", "transcript.sidecar must be null or an object.", 10];
    allowed = {"path", "filename", "sha256", "size_bytes", "media_type", "format"};
    validateExactKeys[sidecar, allowed, "transcript.sidecar"];
    ensureCondition[directChildPathQ[sidecar["path"], "transcripts"], InvalidInputException, "INVALID_TRANSCRIPT_PATH", "transcript.sidecar.path must be one safe direct child of transcripts/.", 10];
    ensureCondition[StringQ[sidecar["filename"]] && sidecar["filename"] === FileNameTake[StringReplace[sidecar["path"], "/" -> $PathnameSeparator]], InvalidInputException, "INVALID_TRANSCRIPT_FILENAME", "transcript.sidecar.filename must match its path.", 10];
    ensureCondition[sha256StringQ[sidecar["sha256"]], InvalidInputException, "INVALID_TRANSCRIPT_HASH", "transcript.sidecar.sha256 must be a lowercase SHA-256 digest.", 10];
    ensureCondition[IntegerQ[sidecar["size_bytes"]] && sidecar["size_bytes"] > 0, InvalidInputException, "INVALID_TRANSCRIPT_SIZE", "transcript.sidecar.size_bytes must be positive.", 10];
    extension = ToLowerCase[FileExtension[sidecar["filename"]]];
    expected = Lookup[<|
        "txt" -> {"text/plain", "txt"},
        "srt" -> {"application/x-subrip", "srt"},
        "vtt" -> {"text/vtt", "vtt"}
    |>, extension, Missing["Unsupported"]];
    ensureCondition[ListQ[expected] && {sidecar["media_type"], sidecar["format"]} === expected, InvalidInputException, "UNSUPPORTED_TRANSCRIPT_FORMAT", "Transcript sidecars must be matching .txt, .srt, or .vtt files.", 10];
    sidecar
];

validateTranscriptConfig[transcript_] := Module[{mode, sidecar},
    ensureCondition[AssociationQ[transcript], InvalidInputException, "INVALID_TRANSCRIPT_CONFIG", "transcript must be an object.", 10];
    validateExactKeys[transcript, {"mode", "sidecar"}, "transcript"];
    mode = transcript["mode"];
    ensureCondition[MemberQ[{"automatic", "prefer_sidecar", "sidecar", "disabled"}, mode], InvalidInputException, "INVALID_TRANSCRIPT_MODE", "transcript.mode is unsupported.", 10];
    sidecar = validateTranscriptSidecar[transcript["sidecar"]];
    ensureCondition[mode =!= "sidecar" || AssociationQ[sidecar], InvalidInputException, "TRANSCRIPT_SIDECAR_REQUIRED", "sidecar mode requires a verified transcript sidecar.", 10];
    ensureCondition[mode =!= "disabled" || sidecar === Null, InvalidInputException, "TRANSCRIPT_DISABLED_WITH_SIDECAR", "disabled transcript mode requires a null sidecar.", 10];
    transcript
];

validateParameters[parameters_] := Module[{frame, hop, silence, seed},
    ensureCondition[AssociationQ[parameters], InvalidInputException, "INVALID_PARAMETERS", "parameters must be an object.", 10];
    validateExactKeys[parameters, {"silence_threshold_db", "frame_seconds", "hop_seconds", "random_seed"}, "parameters"];
    silence = parameters["silence_threshold_db"];
    frame = parameters["frame_seconds"];
    hop = parameters["hop_seconds"];
    seed = parameters["random_seed"];
    ensureCondition[finiteRealQ[silence] && -120. <= silence <= 0., InvalidInputException, "INVALID_SILENCE_THRESHOLD", "silence_threshold_db must be between -120 and 0.", 10];
    ensureCondition[finiteRealQ[frame] && 0. < frame <= 10., InvalidInputException, "INVALID_FRAME_DURATION", "frame_seconds must be greater than 0 and at most 10.", 10];
    ensureCondition[finiteRealQ[hop] && 0. < hop <= 10., InvalidInputException, "INVALID_HOP_DURATION", "hop_seconds must be greater than 0 and at most 10.", 10];
    ensureCondition[finiteRealQ[frame] && finiteRealQ[hop] && hop <= frame, InvalidInputException, "INVALID_PARTITION_GRANULARITY", "hop_seconds must not exceed frame_seconds.", 10];
    ensureCondition[IntegerQ[seed] && 0 <= seed <= 2147483647, InvalidInputException, "INVALID_RANDOM_SEED", "random_seed must be a non-negative 32-bit integer.", 10];
];

validateAnalysisInput[input_] := Module[{allowed},
    ensureCondition[AssociationQ[input], InvalidInputException, "INVALID_INPUT", "The analysis input must be a JSON object.", 10];
    allowed = {"schema_version", "analysis_id", "object_id", "run_id", "package_sha256", "source", "transcript", "evidence", "output_directory", "parameters"};
    validateExactKeys[input, allowed, "input"];
    ensureCondition[input["schema_version"] === $analysisSchemaVersion, InvalidInputException, "UNSUPPORTED_SCHEMA_VERSION", "Unsupported analysis input schema version.", 10];
    ensureCondition[input["analysis_id"] === $analysisID, InvalidInputException, "UNSUPPORTED_ANALYSIS", "Unsupported analysis identifier.", 10];
    ensureCondition[StringQ[input["object_id"]] && StringMatchQ[input["object_id"], RegularExpression["^local-[a-z0-9][a-z0-9-]{0,80}-[a-f0-9]{12}$"]], InvalidInputException, "INVALID_OBJECT_ID", "object_id must be a canonical local media identifier.", 10];
    ensureCondition[StringQ[input["run_id"]] && StringMatchQ[input["run_id"], RegularExpression["^local-[a-f0-9]{16}$"]], InvalidInputException, "INVALID_RUN_ID", "run_id must be a canonical local run identifier.", 10];
    ensureCondition[sha256StringQ[input["package_sha256"]], InvalidInputException, "INVALID_PACKAGE_HASH", "package_sha256 must be a lowercase SHA-256 digest.", 10];
    ensureCondition[input["output_directory"] === "output", InvalidInputException, "INVALID_OUTPUT_DIRECTORY", "output_directory must be output for the local prototype.", 10];
    validateSource[input["source"]];
    validateTranscriptConfig[input["transcript"]];
    validateEvidenceReference[input["evidence"]];
    validateParameters[input["parameters"]];
    input
];

ValidateAnalysisInput[input_] := CatchExceptions[validateAnalysisInput[input], AnalysisException];
