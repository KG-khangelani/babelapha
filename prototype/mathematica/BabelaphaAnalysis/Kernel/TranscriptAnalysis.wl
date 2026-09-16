PackageScoped[analyzeTranscript]
PackageScoped[analyzeTranscriptWithWhisper]
PackageScoped[analyzeTranscriptSidecar]
PackageScoped[whisperTranscriptModelIdentity]

$whisperTranscriptResourceName = "Whisper-V1 Nets";
$whisperTranscriptResourceUUID = "5211d691-293f-417d-a19f-f1e5faef3fb7";
$whisperTranscriptResourceVersion = "1.0.0";
$whisperTranscriptModelSize = "Tiny";
$whisperTranscriptArtifacts = <|
    "audio_encoder" -> <|
        "content_element" -> "EvaluationNet:tiny_encoder",
        "sha256" -> "0c42ff9e0c142bf5f8badf35d9ce337ea9b4d4edce761b31caaebe53c25a464c",
        "size_bytes" -> 32934064
    |>,
    "text_decoder" -> <|
        "content_element" -> "EvaluationNet:tiny_decoder",
        "sha256" -> "4d39de7df517ac91679b4daa9bd359dba0e85a1f9748699090c1c946a7ec4f9a",
        "size_bytes" -> 197918640
    |>,
    "labels" -> <|
        "content_element" -> "Labels",
        "sha256" -> "d3c09f659b7ef46cfaae621574a751fcac71656c6436e997f71129006ccc16ef",
        "size_bytes" -> 437955
    |>
|>;

transcriptSHA256[path_String] := IntegerString[FileHash[path, "SHA256"], 16, 64];

transcriptLocalObjectDirectory[object_LocalObject] := Module[{parts},
    parts = Quiet@Check[URLParse[First[object], "Path"], $Failed];
    If[ListQ[parts] && Length[parts] > 1, FileNameJoin[Rest[parts]], $Failed]
];

transcriptCachedArtifact[locations_Association, name_String, expected_Association] := Module[
    {location, directory, candidates, file, actualHash, actualSize, matches},
    location = Lookup[locations, expected["content_element"], Missing["NotCached"]];
    If[Head[location] =!= LocalObject,
        Return[Join[expected, <|"status" -> "NOT_CACHED", "actual_sha256" -> Null, "actual_size_bytes" -> Null|>]]
    ];
    directory = transcriptLocalObjectDirectory[location];
    If[! StringQ[directory] || ! DirectoryQ[directory],
        Return[Join[expected, <|"status" -> "NOT_CACHED", "actual_sha256" -> Null, "actual_size_bytes" -> Null|>]]
    ];
    candidates = Join[FileNames["*.WLNet", directory], FileNames["*.WXF", directory]];
    If[candidates === {},
        Return[Join[expected, <|"status" -> "NOT_CACHED", "actual_sha256" -> Null, "actual_size_bytes" -> Null|>]]
    ];
    file = First@Sort[candidates];
    actualHash = ToLowerCase@transcriptSHA256[file];
    actualSize = FileByteCount[file];
    matches = actualHash === expected["sha256"] && actualSize === expected["size_bytes"];
    Join[expected, <|
        "status" -> If[matches, "VERIFIED", "HASH_MISMATCH"],
        "actual_sha256" -> actualHash,
        "actual_size_bytes" -> actualSize
    |>]
];

whisperTranscriptModelIdentity[] := Block[{$AllowInternet = False}, Module[
    {resource, uuid, version, locations, artifacts, verified, identityComponents},
    resource = Quiet@Check[
        ResourceObject[$whisperTranscriptResourceUUID, ResourceVersion -> $whisperTranscriptResourceVersion],
        $Failed
    ];
    If[resource === $Failed,
        Return[<|
            "status" -> "NOT_CACHED",
            "reason" -> "The pinned Wolfram Whisper resource metadata is not present in the local object store.",
            "repository_resource_name" -> $whisperTranscriptResourceName,
            "resource_uuid" -> $whisperTranscriptResourceUUID,
            "resource_version" -> $whisperTranscriptResourceVersion,
            "size" -> $whisperTranscriptModelSize,
            "target_device" -> "CPU",
            "network_mode" -> "disabled",
            "artifacts" -> <||>,
            "identity_sha256" -> Null
        |>]
    ];
    uuid = Quiet@Check[resource["UUID"], $Failed];
    version = Quiet@Check[resource["Version"], $Failed];
    locations = Quiet@Check[resource["ContentElementLocations"], $Failed];
    If[uuid =!= $whisperTranscriptResourceUUID || version =!= $whisperTranscriptResourceVersion || ! AssociationQ[locations],
        Return[<|
            "status" -> "IDENTITY_MISMATCH",
            "reason" -> "The cached Wolfram resource does not match the pinned UUID and version.",
            "repository_resource_name" -> $whisperTranscriptResourceName,
            "resource_uuid" -> If[StringQ[uuid], uuid, Null],
            "resource_version" -> If[StringQ[version], version, Null],
            "size" -> $whisperTranscriptModelSize,
            "target_device" -> "CPU",
            "network_mode" -> "disabled",
            "artifacts" -> <||>,
            "identity_sha256" -> Null
        |>]
    ];
    artifacts = Association@KeyValueMap[
        Function[{name, expected}, name -> transcriptCachedArtifact[locations, name, expected]],
        $whisperTranscriptArtifacts
    ];
    verified = AllTrue[Values[artifacts], Lookup[#, "status", ""] === "VERIFIED" &];
    identityComponents = Join[
        {$whisperTranscriptResourceUUID, $whisperTranscriptResourceVersion, $whisperTranscriptModelSize},
        Flatten@KeyValueMap[{#1, #2["actual_sha256"], ToString[#2["actual_size_bytes"]]} &, artifacts]
    ];
    <|
        "status" -> If[verified, "VERIFIED", "NOT_CACHED"],
        "reason" -> If[verified, "", "One or more pinned model artifacts are absent or do not match their expected SHA-256 digest."],
        "repository_resource_name" -> $whisperTranscriptResourceName,
        "resource_uuid" -> uuid,
        "resource_version" -> version,
        "size" -> $whisperTranscriptModelSize,
        "target_device" -> "CPU",
        "network_mode" -> "disabled",
        "artifacts" -> artifacts,
        "identity_sha256" -> If[
            verified,
            IntegerString[Hash[StringRiffle[identityComponents, "\n"], "SHA256"], 16, 64],
            Null
        ]
    |>
]];

transcriptTimestampSeconds[label_String] := Module[{matches},
    matches = StringCases[
        label,
        StartOfString ~~ "|" ~~ value : NumberString ~~ "|" ~~ EndOfString :>
            Quiet@Check[ToExpression[value], Missing["InvalidTimestamp"]]
    ];
    If[Length[matches] == 1 && NumericQ[First[matches]], N[First[matches]], Missing["NotTimestamp"]]
];

transcriptSpecialTokenQ[label_String] := StringMatchQ[label, StartOfString ~~ "|" ~~ ___ ~~ "|" ~~ EndOfString];

transcriptGreedyToken[probabilities_, suppressed_List] := Module[{scores},
    scores = ReplacePart[N[probabilities], Thread[suppressed -> -Infinity]];
    First@FirstPosition[scores, Max[scores]]
];

transcriptDecodeWhisperChunk[features_, decoder_, maxIterations_Integer] := Module[
    {eosCode = 50257, sosCode = 50258, noTimestampsCode = 50363, index = 1,
     initialStates, outputPorts, state, networkOutput, token, tokens = {}},
    initialStates = AssociationMap[
        Function[name, {}],
        Select[Information[decoder, "InputPortNames"], StringStartsQ["State"]]
    ];
    outputPorts = Append[
        NetPort /@ Information[decoder, "OutputPortNames"],
        NetPort[{"softmax", "Output"}]
    ];
    state = Join[<|"Index" -> index, "Input1" -> sosCode, "Input2" -> features|>, initialStates];
    Do[
        networkOutput = decoder[state, outputPorts, TargetDevice -> "CPU"];
        token = transcriptGreedyToken[
            networkOutput[NetPort[{"softmax", "Output"}]],
            {noTimestampsCode}
        ];
        If[token === eosCode, Break[]];
        AppendTo[tokens, token];
        state = Join[
            KeyMap[
                StringReplace["OutState" -> "State"],
                KeyDrop[networkOutput, NetPort[{"softmax", "Output"}]]
            ],
            <|"Index" -> ++index, "Input1" -> token, "Input2" -> features|>
        ],
        {maxIterations}
    ];
    tokens
];

transcriptSegmentsFromLabels[labels_List, offset_?NumericQ, chunkDuration_?NumericQ] := Module[
    {segments = {}, start = Missing["NotStarted"], buffer = "", timestamp, clean, finish, chunkEnd},
    chunkEnd = N[offset + chunkDuration];
    Do[
        timestamp = transcriptTimestampSeconds[label];
        If[NumericQ[timestamp],
            If[MissingQ[start],
                start = Min[chunkEnd, N[offset + timestamp]],
                clean = StringTrim[buffer];
                finish = Min[chunkEnd, N[offset + timestamp]];
                If[clean =!= "" && finish >= start,
                    AppendTo[segments, <|"start_seconds" -> start, "end_seconds" -> finish, "text" -> clean|>]
                ];
                start = finish;
                buffer = ""
            ],
            If[! transcriptSpecialTokenQ[label], buffer = buffer <> label]
        ],
        {label, labels}
    ];
    clean = StringTrim[buffer];
    If[clean =!= "",
        If[MissingQ[start], start = N[offset]];
        finish = chunkEnd;
        If[finish >= start,
            AppendTo[segments, <|"start_seconds" -> start, "end_seconds" -> finish, "text" -> clean|>]
        ]
    ];
    segments
];

$transcriptStopWords = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "hers", "him", "his", "i", "in", "is", "it",
    "its", "me", "my", "of", "on", "or", "our", "ours", "she", "so", "that", "the",
    "their", "theirs", "them", "they", "this", "to", "was", "we", "were", "with", "you", "your"
};

transcriptStatistics[text_String, segments_List, duration_] := Module[
    {words, normalized, terms, ranked, wordCount, uniqueCount, durationSeconds, sentenceParts, starts, ends},
    words = TextWords[text];
    normalized = ToLowerCase /@ Select[words, StringMatchQ[#, LetterCharacter ..] &];
    terms = Select[normalized, StringLength[#] >= 3 && ! MemberQ[$transcriptStopWords, #] &];
    ranked = SortBy[Normal@Counts[terms], {(-Last[#]) &, First[#] &}];
    wordCount = Length[normalized];
    uniqueCount = Length@DeleteDuplicates[normalized];
    starts = Select[Lookup[segments, "start_seconds", {}], NumericQ];
    ends = Select[Lookup[segments, "end_seconds", {}], NumericQ];
    durationSeconds = Which[
        NumericQ[duration] && duration > 0, N[duration],
        starts =!= {} && ends =!= {}, N[Max[ends] - Min[starts]],
        True, Null
    ];
    sentenceParts = DeleteCases[StringTrim /@ StringSplit[text, RegularExpression["[.!?]+\\s*"]], ""];
    <|
        "character_count" -> StringLength[text],
        "word_count" -> wordCount,
        "sentence_count" -> If[text === "", 0, Max[1, Length[sentenceParts]]],
        "unique_word_count" -> uniqueCount,
        "lexical_diversity" -> If[wordCount > 0, N[uniqueCount/wordCount], Null],
        "words_per_minute" -> If[NumericQ[durationSeconds] && durationSeconds > 0, N[60. wordCount/durationSeconds], Null],
        "top_terms" -> (<|"term" -> First[#], "count" -> Last[#]|> & /@ Take[ranked, UpTo[15]])
    |>
];

transcriptUnavailable[method_String, reason_String, model_: Null] := <|
    "status" -> "UNAVAILABLE",
    "reason" -> reason,
    "method" -> method,
    "text" -> "",
    "segments" -> {},
    "statistics" -> transcriptStatistics["", {}, Null],
    "model" -> model,
    "sidecar" -> Null,
    "inference" -> Null
|>;

analyzeTranscriptWithWhisper[audio_?AudioQ] := Block[{$AllowInternet = False}, Module[
    {model, encoder, decoder, labels, chunks, features, tokenChunks, labelChunks,
     audioDuration, chunkDurations, segments, text, result},
    model = whisperTranscriptModelIdentity[];
    If[Lookup[model, "status", ""] =!= "VERIFIED",
        Return@transcriptUnavailable[
            "wolfram_whisper_v1_tiny",
            "The pinned Whisper-V1 Tiny model is not fully cached and verified. Run the explicit model-cache preparation step while online, then retry locally.",
            model
        ]
    ];
    result = Quiet@Check[
        encoder = NetModel[{$whisperTranscriptResourceName, "Size" -> $whisperTranscriptModelSize, "Part" -> "AudioEncoder"}];
        decoder = NetModel[{$whisperTranscriptResourceName, "Size" -> $whisperTranscriptModelSize, "Part" -> "TextDecoder"}];
        labels = NetModel[$whisperTranscriptResourceName, "Labels"];
        audioDuration = N@QuantityMagnitude@UnitConvert[Duration[audio], "Seconds"];
        chunks = AudioPartition[audio, 30];
        features = encoder[chunks, TargetDevice -> "CPU"];
        tokenChunks = transcriptDecodeWhisperChunk[#, decoder, 224] & /@ features;
        labelChunks = (labels[[#]] &) /@ tokenChunks;
        chunkDurations = Table[Min[30., Max[0., audioDuration - 30. (index - 1)]], {index, Length[labelChunks]}];
        segments = Flatten@MapThread[
            transcriptSegmentsFromLabels[#1, 30. (#3 - 1), #2] &,
            {labelChunks, chunkDurations, Range[Length[labelChunks]]}
        ];
        text = StringTrim@StringJoin@Flatten@Map[
            Select[#, ! transcriptSpecialTokenQ[#] &] &,
            labelChunks
        ];
        <|
            "status" -> If[text === "", "UNAVAILABLE", "AVAILABLE"],
            "reason" -> If[text === "", "The local model returned no speech text.", ""],
            "method" -> "wolfram_whisper_v1_tiny",
            "text" -> text,
            "segments" -> segments,
            "statistics" -> transcriptStatistics[text, segments, audioDuration],
            "model" -> model,
            "sidecar" -> Null,
            "inference" -> <|
                "chunk_seconds" -> 30.,
                "chunk_count" -> Length[chunks],
                "max_tokens_per_chunk" -> 224,
                "sampling" -> "greedy_argmax",
                "temperature" -> 0.,
                "target_device" -> "CPU",
                "network_mode" -> "disabled"
            |>
        |>,
        $Failed
    ];
    If[result === $Failed,
        transcriptUnavailable[
            "wolfram_whisper_v1_tiny",
            "Offline inference with the verified local Whisper-V1 Tiny model failed.",
            model
        ],
        result
    ]
]];

analyzeTranscriptWithWhisper[_] := transcriptUnavailable[
    "wolfram_whisper_v1_tiny",
    "No decodable audio track was provided for automatic transcription.",
    whisperTranscriptModelIdentity[]
];

transcriptDecimalSeconds[value_String] := Module[{normalized, parts, secondsParts, seconds},
    normalized = StringReplace[StringTrim[value], "," -> "."];
    parts = StringSplit[normalized, ":"];
    If[! MemberQ[{2, 3}, Length[parts]] || ! AllTrue[Most[parts], StringMatchQ[#, DigitCharacter ..] &], Return[$Failed]];
    secondsParts = StringSplit[Last[parts], "."];
    If[! MemberQ[{1, 2}, Length[secondsParts]] || ! AllTrue[secondsParts, StringMatchQ[#, DigitCharacter ..] &], Return[$Failed]];
    seconds = N[FromDigits[First[secondsParts]] + If[Length[secondsParts] == 2, FromDigits[Last[secondsParts]]/10.^StringLength[Last[secondsParts]], 0.]];
    If[Length[parts] == 3,
        N[3600 FromDigits[parts[[1]]] + 60 FromDigits[parts[[2]]] + seconds],
        N[60 FromDigits[parts[[1]]] + seconds]
    ]
];

transcriptCleanCueText[lines_List] := StringTrim@StringRiffle[
    Select[
        StringTrim@StringReplace[lines, {
            RegularExpression["<[^>]+>"] -> "",
            "&amp;" -> "&", "&lt;" -> "<", "&gt;" -> ">", "&nbsp;" -> " "
        }],
        # =!= "" &
    ],
    " "
];

transcriptCueFromBlock[block_String] := Module[
    {lines, timingPosition, timing, endpoints, start, finish, text},
    lines = StringSplit[StringTrim[block], "\n"];
    timingPosition = FirstPosition[lines, _String?(StringContainsQ[#, "-->"] &), Missing["NotFound"]];
    If[MissingQ[timingPosition], Return[Nothing]];
    timing = lines[[First[timingPosition]]];
    endpoints = StringTrim /@ StringSplit[timing, "-->"];
    If[Length[endpoints] =!= 2, Return[Nothing]];
    start = transcriptDecimalSeconds[First@endpoints];
    finish = transcriptDecimalSeconds[First@StringSplit[Last@endpoints]];
    If[! NumericQ[start] || ! NumericQ[finish] || finish < start, Return[Nothing]];
    text = transcriptCleanCueText[Drop[lines, First[timingPosition]]];
    If[text === "", Return[Nothing]];
    <|"start_seconds" -> start, "end_seconds" -> finish, "text" -> text|>
];

transcriptTimedSidecarSegments[content_String] := Module[{normalized, blocks},
    normalized = StringReplace[content, {"\r\n" -> "\n", "\r" -> "\n", StartOfString ~~ FromCharacterCode[65279] -> ""}];
    blocks = StringSplit[normalized, RegularExpression["\n[ \\t]*\n+"]];
    Cases[transcriptCueFromBlock /@ blocks, _Association]
];

analyzeTranscriptSidecar[path_String, mediaDuration_: Null] := Module[
    {absolute, extension, content, segments, text, duration},
    absolute = ExpandFileName[path];
    If[! FileExistsQ[absolute], Return@transcriptUnavailable["sidecar", "The configured transcript sidecar does not exist."]];
    extension = ToLowerCase@FileExtension[absolute];
    If[! MemberQ[{"txt", "srt", "vtt"}, extension],
        Return@transcriptUnavailable["sidecar", "Transcript sidecars must use .txt, .srt, or .vtt format."]
    ];
    content = Quiet@Check[Import[absolute, "Text"], $Failed];
    If[! StringQ[content], Return@transcriptUnavailable["sidecar", "The transcript sidecar could not be decoded as text."]];
    If[extension === "txt",
        text = StringTrim@StringReplace[content, StartOfString ~~ FromCharacterCode[65279] -> ""];
        segments = If[text === "", {}, {<|"start_seconds" -> 0., "end_seconds" -> If[NumericQ[mediaDuration], N[mediaDuration], Null], "text" -> text|>}],
        segments = transcriptTimedSidecarSegments[content];
        text = StringTrim@StringRiffle[Lookup[segments, "text", {}], " "]
    ];
    If[NumericQ[mediaDuration] && ! AllTrue[
        segments,
        0. <= Lookup[#, "start_seconds", -1.] <= Lookup[#, "end_seconds", -1.] <= N[mediaDuration] &
    ],
        Return@transcriptUnavailable["sidecar", "A transcript sidecar cue falls outside the media duration."]
    ];
    If[text === "", Return@transcriptUnavailable["sidecar", "The transcript sidecar contains no usable transcript text."]];
    duration = If[NumericQ[mediaDuration], N[mediaDuration], Null];
    <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "method" -> "sidecar",
        "text" -> text,
        "segments" -> segments,
        "statistics" -> transcriptStatistics[text, segments, duration],
        "sidecar" -> <|
            "format" -> extension,
            "sha256" -> ToLowerCase@transcriptSHA256[absolute],
            "size_bytes" -> FileByteCount[absolute]
        |>,
        "model" -> Null,
        "inference" -> Null
    |>
];

analyzeTranscriptSidecar[_, ___] := transcriptUnavailable["sidecar", "A transcript sidecar path string is required."];

analyzeTranscript[audio_, config_Association] := Module[
    {mode, sidecarPath, duration},
    mode = ToLowerCase@ToString@Lookup[config, "mode", "automatic"];
    sidecarPath = Lookup[config, "sidecar_path", Null];
    duration = Lookup[config, "media_duration_seconds", Null];
    Switch[mode,
        "disabled", transcriptUnavailable["disabled", "Transcript analysis was explicitly disabled."],
        "sidecar", analyzeTranscriptSidecar[sidecarPath, duration],
        "auto" | "prefer_sidecar",
            If[StringQ[sidecarPath] && FileExistsQ[sidecarPath],
                analyzeTranscriptSidecar[sidecarPath, duration],
                analyzeTranscriptWithWhisper[audio]
            ],
        "automatic" | "whisper", analyzeTranscriptWithWhisper[audio],
        _, transcriptUnavailable["configuration", "Unknown transcript analysis mode: " <> mode]
    ]
];

analyzeTranscript[audio_] := analyzeTranscript[audio, <|"mode" -> "automatic"|>];
