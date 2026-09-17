#!/usr/bin/env wolframscript

scriptDirectory = DirectoryName[ExpandFileName[$InputFileName]];
notebookPath = FileNameJoin[{scriptDirectory, "BabelaphaAnalysis.nb"}];
runtimeLoader = FileNameJoin[{scriptDirectory, "notebook-runtime.wls"}];

If[! FileExistsQ[notebookPath] || ! FileExistsQ[runtimeLoader],
    WriteString[$Output, "The canonical Babelapha Mathematica notebook or its thin runtime loader was not found.\n"];
    Exit[12]
];

Get[runtimeLoader];

arguments = Rest[$ScriptCommandLine];
inputPosition = FirstPosition[arguments, "--input", Missing["NotFound"]];

If[MissingQ[inputPosition] || First[inputPosition] >= Length[arguments],
    WriteString[$Output, "Usage: wolframscript -file analyze.wls --input <analysis-input.json>\n"];
    Exit[2]
];

inputPath = arguments[[First[inputPosition] + 1]];
Global`$BabelaphaNotebookSourcePath = notebookPath;
Global`$BabelaphaNotebookInputPath = ExpandFileName[inputPath];

If[BabelaphaNotebookEvaluateTag[notebookPath, "BabelaphaDefinitions"] === $Failed,
    WriteString[$Output, "The canonical notebook definitions could not be evaluated.\n"];
    Exit[12]
];

result = BabelaphaNotebookEvaluateTag[notebookPath, "BabelaphaRun"];

If[FailureQ[result],
    WriteString[
        $Output,
        ExportString[
            <|
                "status" -> "FAILED",
                "reason" -> BabelaphaNotebook`FailureReason[result],
                "message" -> Lookup[result[[2]], "Message", "Mathematica analysis failed."],
                "exit_code" -> BabelaphaNotebook`FailureExitCode[result],
                "details" -> KeyTake[
                    result[[2]],
                    {"Path", "Format", "Expected", "Actual", "Index", "Location"}
                ]
            |>,
            "RawJSON"
        ] <> "\n"
    ];
    Exit[BabelaphaNotebook`FailureExitCode[result]]
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
