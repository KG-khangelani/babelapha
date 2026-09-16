#!/usr/bin/env wolframscript

scriptDirectory = DirectoryName[ExpandFileName[$InputFileName]];
packageLoader = FileNameJoin[{scriptDirectory, "BabelaphaAnalysis", "Kernel", "init.wl"}];

If[! FileExistsQ[packageLoader],
    WriteString[$Output, "BabelaphaAnalysis package loader not found.\n"];
    Exit[12]
];

Get[packageLoader];

arguments = Rest[$ScriptCommandLine];
inputPosition = FirstPosition[arguments, "--input", Missing["NotFound"]];

If[MissingQ[inputPosition] || First[inputPosition] >= Length[arguments],
    WriteString[$Output, "Usage: wolframscript -file analyze.wls --input <analysis-input.json>\n"];
    Exit[2]
];

inputPath = arguments[[First[inputPosition] + 1]];
result = BabelaphaAnalysis`RunAnalysisFile[inputPath];

If[FailureQ[result],
    WriteString[
        $Output,
        ExportString[
            <|
                "status" -> "FAILED",
                "reason" -> BabelaphaAnalysis`FailureReason[result],
                "message" -> Lookup[result[[2]], "Message", "Mathematica analysis failed."],
                "exit_code" -> BabelaphaAnalysis`FailureExitCode[result],
                "details" -> KeyTake[
                    result[[2]],
                    {"Path", "Format", "Expected", "Actual", "Index", "Location"}
                ]
            |>,
            "RawJSON"
        ] <> "\n"
    ];
    Exit[BabelaphaAnalysis`FailureExitCode[result]]
];

WriteString[
    $Output,
    ExportString[
        <|
            "status" -> "SUCCEEDED",
            "analysis_id" -> result["analysis_id"],
            "object_id" -> result["object_id"],
            "run_id" -> result["run_id"],
            "output_count" -> Length[result["outputs"]]
        |>,
        "RawJSON"
    ] <> "\n"
];
Exit[0]
