PackageExported[RunAnalysisFile]
PackageExported[PackageSourceHash]

PackageScoped[runAnalysisFileImplementation]

$packageKernelDirectory = DirectoryName[$InputFileName];

PackageSourceHash[] := Module[{files, components},
    files = Sort[FileNames["*.wl", $packageKernelDirectory]];
    components = (FileNameTake[#] <> ":" <> fileSHA256[#]) & /@ files;
    IntegerString[Hash[StringRiffle[components, "\n"], "SHA256"], 16, 64]
];

workspaceRootForInput[inputPath_String] := Module[{directory},
    directory = DirectoryName[ExpandFileName[inputPath]];
    If[ToLowerCase[FileNameTake[directory]] === "artefacts", DirectoryName[directory], directory]
];

importAnalysisInput[inputPath_String] := Module[{input},
    ensureCondition[FileExistsQ[inputPath], InvalidInputException, "INPUT_NOT_FOUND", "The analysis input file does not exist.", 10, <|"Path" -> inputPath|>];
    input = Quiet[Check[Import[inputPath, "RawJSON"], $Failed]];
    ensureCondition[AssociationQ[input], InvalidInputException, "INVALID_INPUT_JSON", "The analysis input could not be imported as a JSON object.", 10, <|"Path" -> inputPath|>];
    validateAnalysisInput[input]
];

verifySource[input_Association, workspaceRoot_String] := Module[{source, path, actualHash, actualSize},
    source = input["source"];
    path = resolveWorkspacePath[workspaceRoot, source["path"]];
    ensureCondition[FileExistsQ[path], IntegrityException, "SOURCE_NOT_FOUND", "The selected source video does not exist.", 11, <|"Path" -> path|>];
    actualHash = fileSHA256[path];
    actualSize = FileByteCount[path];
    ensureCondition[actualHash === source["sha256"], IntegrityException, "SOURCE_HASH_MISMATCH", "The selected source SHA-256 digest does not match the analysis input.", 11, <|"Expected" -> source["sha256"], "Actual" -> actualHash|>];
    ensureCondition[actualSize === source["size_bytes"], IntegrityException, "SOURCE_SIZE_MISMATCH", "The selected source byte size does not match the analysis input.", 11, <|"Expected" -> source["size_bytes"], "Actual" -> actualSize|>];
    path
];

runAnalysisFileImplementation[inputPath_String] := Module[
    {absoluteInput, workspaceRoot, input, sourcePath, evidence, media, outputDirectory,
     audioSummary, measurements, provenance, exported, result},
    absoluteInput = ExpandFileName[inputPath];
    workspaceRoot = workspaceRootForInput[absoluteInput];
    input = importAnalysisInput[absoluteInput];
    ensureCondition[
        PackageSourceHash[] === input["package_sha256"],
        IntegrityException,
        "PACKAGE_HASH_MISMATCH",
        "The loaded Wolfram package SHA-256 does not match the prepared analysis input.",
        11,
        <|"Expected" -> input["package_sha256"], "Actual" -> PackageSourceHash[]|>
    ];
    sourcePath = verifySource[input, workspaceRoot];
    evidence = loadVerifiedEvidence[input, workspaceRoot];
    media = analyzeMedia[sourcePath, input["parameters"]];
    audioSummary = media["audio_analysis", "summary"];
    measurements = Join[
        audioSummary,
        <|
            "duration_seconds" -> media["duration_seconds"],
            "video" -> media["video_summary"],
            "evidence_events" -> evidence["event_summary"],
            "tabular_summary" -> evidence["tabular_summary"]
        |>
    ];
    provenance = evidence["summary"];
    outputDirectory = resolveWorkspacePath[workspaceRoot, input["output_directory"]];
    exported = exportAnalysisArtifacts[
        input,
        media,
        measurements,
        provenance,
        outputDirectory,
        FileNameJoin[{$packageKernelDirectory, "init.wl"}],
        absoluteInput
    ];
    result = <|
        "schema_version" -> $analysisSchemaVersion,
        "analysis_id" -> $analysisID,
        "object_id" -> input["object_id"],
        "run_id" -> input["run_id"],
        "processor" -> <|
            "name" -> "BabelaphaAnalysis",
            "wolfram_version" -> $Version,
            "system_id" -> $SystemID,
            "package_sha256" -> input["package_sha256"],
            "network_mode" -> "disabled"
        |>,
        "source" -> input["source"],
        "evidence" -> input["evidence"],
        "parameters" -> input["parameters"],
        "capabilities" -> exported["capabilities"],
        "measurements" -> measurements,
        "provenance_summary" -> provenance,
        "outputs" -> exported["outputs"]
    |>;
    writeRawResult[result, outputDirectory];
    result
];

RunAnalysisFile[inputPath_String] := CatchExceptions[
    Block[{$AllowInternet = False}, runAnalysisFileImplementation[inputPath]],
    AnalysisException
];

RunAnalysisFile[_] := Failure["InvalidInputPath", <|"Reason" -> "INVALID_INPUT_PATH", "Message" -> "RunAnalysisFile expects one path string.", "ExitCode" -> 10|>];
