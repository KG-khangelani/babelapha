PackageScoped[loadVerifiedEvidence]

loadJSONFile[path_String, reason_String] := Module[{value},
    value = Quiet[Check[Import[path, "RawJSON"], $Failed]];
    ensureCondition[
        AssociationQ[value],
        InvalidInputException,
        reason,
        "A required JSON document could not be imported as an object.",
        10,
        <|"Path" -> path|>
    ];
    value
];

validateEvidenceEvent[event_, index_Integer] := Module[{allowed},
    ensureCondition[AssociationQ[event], IntegrityException, "INVALID_EVIDENCE_EVENT", "Every evidence event must be an object.", 11, <|"Index" -> index|>];
    allowed = {"sequence", "event_type", "stage", "status", "artifact_count"};
    ensureCondition[Sort[Keys[event]] === Sort[allowed], IntegrityException, "INVALID_EVIDENCE_EVENT", "An evidence event has missing or unknown fields.", 11, <|"Index" -> index|>];
    ensureCondition[IntegerQ[event["sequence"]] && event["sequence"] >= 1, IntegrityException, "INVALID_EVIDENCE_SEQUENCE", "Evidence sequence values must be positive integers.", 11, <|"Index" -> index|>];
    ensureCondition[StringQ[event["event_type"]] && StringLength[event["event_type"]] > 0, IntegrityException, "INVALID_EVIDENCE_EVENT_TYPE", "Evidence event_type must be a non-empty string.", 11, <|"Index" -> index|>];
    ensureCondition[StringQ[event["stage"]] && StringLength[event["stage"]] > 0, IntegrityException, "INVALID_EVIDENCE_STAGE", "Evidence stage must be a non-empty string.", 11, <|"Index" -> index|>];
    ensureCondition[event["status"] === "SUCCEEDED", IntegrityException, "UNSUCCESSFUL_EVIDENCE_EVENT", "Only successful evidence events can feed the local analysis.", 11, <|"Index" -> index|>];
    ensureCondition[IntegerQ[event["artifact_count"]] && event["artifact_count"] >= 1, IntegrityException, "INVALID_EVIDENCE_ARTIFACT_COUNT", "Evidence artifact_count must be a positive integer.", 11, <|"Index" -> index|>];
];

loadVerifiedEvidence[input_Association, workspaceRoot_String] := Module[
    {reference, path, evidence, actualHash, events, eventKeys, eventSeries, table,
     sequences, allowed, expectedEvents, actualEvents},
    reference = input["evidence"];
    path = resolveWorkspacePath[workspaceRoot, reference["path"]];
    ensureCondition[FileExistsQ[path], IntegrityException, "EVIDENCE_NOT_FOUND", "The source evidence file does not exist.", 11, <|"Path" -> path|>];
    actualHash = fileSHA256[path];
    ensureCondition[actualHash === reference["sha256"], IntegrityException, "EVIDENCE_HASH_MISMATCH", "The source evidence SHA-256 digest does not match the analysis input.", 11, <|"Expected" -> reference["sha256"], "Actual" -> actualHash|>];
    evidence = loadJSONFile[path, "INVALID_EVIDENCE_JSON"];
    allowed = {"schema_version", "evidence_type", "canonicalization", "object_id", "run_id", "source", "transcript_sidecar", "events"};
    ensureCondition[Sort[Keys[evidence]] === Sort[allowed], IntegrityException, "INVALID_EVIDENCE_FIELDS", "The source evidence has missing or unknown fields.", 11];
    ensureCondition[evidence["schema_version"] === "2.0.0" && evidence["evidence_type"] === "BABELAPHA_LOCAL_SOURCE_V2", IntegrityException, "UNSUPPORTED_EVIDENCE", "The evidence document has an unsupported type or version.", 11];
    ensureCondition[evidence["canonicalization"] === "SORTED_INDENTED_JSON_V1", IntegrityException, "UNSUPPORTED_EVIDENCE_CANONICALIZATION", "The evidence document uses an unsupported canonicalization.", 11];
    ensureCondition[evidence["object_id"] === input["object_id"] && evidence["run_id"] === input["run_id"], IntegrityException, "EVIDENCE_IDENTITY_MISMATCH", "Evidence object/run identity does not match the analysis input.", 11];
    ensureCondition[AssociationQ[evidence["source"]] && KeySort[evidence["source"]] === KeySort[input["source"]], IntegrityException, "EVIDENCE_SOURCE_MISMATCH", "Evidence source identity does not match the selected source.", 11];
    ensureCondition[Lookup[evidence, "transcript_sidecar", Missing["NotAvailable"]] === input["transcript", "sidecar"], IntegrityException, "EVIDENCE_TRANSCRIPT_MISMATCH", "Evidence transcript-sidecar identity does not match the analysis input.", 11];
    events = Lookup[evidence, "events", Missing["NotAvailable"]];
    expectedEvents = If[input["transcript", "sidecar"] === Null,
        {
            {1, "SOURCE_DISCOVERED", "ingest", "SUCCEEDED", 1},
            {2, "SOURCE_HASH_VERIFIED", "prepare", "SUCCEEDED", 1}
        },
        {
            {1, "SOURCE_DISCOVERED", "ingest", "SUCCEEDED", 1},
            {2, "SOURCE_HASH_VERIFIED", "prepare", "SUCCEEDED", 1},
            {3, "TRANSCRIPT_SOURCE_DISCOVERED", "transcripts", "SUCCEEDED", 2},
            {4, "TRANSCRIPT_SOURCE_HASH_VERIFIED", "prepare", "SUCCEEDED", 2}
        }
    ];
    ensureCondition[ListQ[events] && Length[events] === Length[expectedEvents], IntegrityException, "INVALID_EVIDENCE_EVENTS", "Evidence must contain the exact canonical local trust events.", 11];
    MapIndexed[validateEvidenceEvent[#1, First[#2]] &, events];
    actualEvents = ({#1["sequence"], #1["event_type"], #1["stage"], #1["status"], #1["artifact_count"]} &) /@ events;
    ensureCondition[actualEvents === expectedEvents, IntegrityException, "NONCANONICAL_EVIDENCE_EVENTS", "Evidence events differ from the canonical local trust sequence.", 11];
    sequences = Lookup[events, "sequence"];
    ensureCondition[DuplicateFreeQ[sequences] && OrderedQ[sequences], IntegrityException, "INVALID_EVIDENCE_ORDER", "Evidence event sequences must be unique and ordered.", 11];
    eventKeys = {"event_type", "stage", "status", "artifact_count"};
    eventSeries = Quiet[Check[EventSeries[Lookup[events, eventKeys], {sequences}, eventKeys], $Failed]];
    ensureCondition[Head[eventSeries] === EventSeries, DependencyException, "EVENT_SERIES_UNAVAILABLE", "Wolfram EventSeries construction failed.", 12];
    table = Quiet[Check[Tabular[events], $Failed]];
    ensureCondition[Head[table] === Tabular, DependencyException, "TABULAR_UNAVAILABLE", "Wolfram Tabular construction failed.", 12];
    <|
        "document" -> evidence,
        "path" -> path,
        "sha256" -> actualHash,
        "events" -> events,
        "event_series" -> eventSeries,
        "table" -> table,
        "summary" -> <|
            "task_count" -> Length[events],
            "artifact_count" -> Last[Lookup[events, "artifact_count"]],
            "integrity_conflict_count" -> 0,
            "evidence_sha256" -> actualHash
        |>,
        "event_summary" -> <|
            "event_count" -> Length[Normal[eventSeries]],
            "event_types" -> Sort[DeleteDuplicates[Lookup[events, "event_type"]]]
        |>,
        "tabular_summary" -> <|
            "row_count" -> First[Dimensions[table]],
            "column_names" -> (If[StringQ[#], #, ToString[#, InputForm]] & /@ ColumnKeys[table])
        |>
    |>
];
