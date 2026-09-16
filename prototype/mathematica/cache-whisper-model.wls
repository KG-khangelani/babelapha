#!/usr/bin/env wolframscript

scriptDirectory = DirectoryName[ExpandFileName[$InputFileName]];
packageLoader = FileNameJoin[{scriptDirectory, "BabelaphaAnalysis", "Kernel", "init.wl"}];

If[! FileExistsQ[packageLoader],
    WriteString[$Output, "BabelaphaAnalysis package loader not found.\n"];
    Exit[12]
];

$AllowInternet = True;
encoder = Quiet@Check[
    NetModel[{"Whisper-V1 Nets", "Size" -> "Tiny", "Part" -> "AudioEncoder"}],
    $Failed
];
decoder = Quiet@Check[
    NetModel[{"Whisper-V1 Nets", "Size" -> "Tiny", "Part" -> "TextDecoder"}],
    $Failed
];
labels = Quiet@Check[NetModel["Whisper-V1 Nets", "Labels"], $Failed];

If[MemberQ[{encoder, decoder, labels}, $Failed],
    WriteString[$Output, ExportString[<|
        "status" -> "FAILED",
        "reason" -> "WHISPER_MODEL_CACHE_FAILED"
    |>, "RawJSON"] <> "\n"];
    Exit[12]
];

$AllowInternet = False;
Get[packageLoader];
identity = BabelaphaAnalysis`PackageScope`whisperTranscriptModelIdentity[];

WriteString[$Output, ExportString[<|
    "status" -> Lookup[identity, "status", "FAILED"],
    "resource_uuid" -> Lookup[identity, "resource_uuid", Null],
    "resource_version" -> Lookup[identity, "resource_version", Null],
    "size" -> Lookup[identity, "size", Null],
    "identity_sha256" -> Lookup[identity, "identity_sha256", Null],
    "network_mode_after_cache" -> "disabled"
|>, "RawJSON"] <> "\n"];

If[Lookup[identity, "status", ""] === "VERIFIED", Exit[0], Exit[12]];
