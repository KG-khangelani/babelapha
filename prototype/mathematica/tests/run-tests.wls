#!/usr/bin/env wolframscript

testDirectory = DirectoryName[ExpandFileName[$InputFileName]];
prototypeDirectory = DirectoryName[testDirectory];
notebookPath = FileNameJoin[{prototypeDirectory, "BabelaphaAnalysis.nb"}];
runtimeLoader = FileNameJoin[{prototypeDirectory, "notebook-runtime.wls"}];

If[! FileExistsQ[notebookPath] || ! FileExistsQ[runtimeLoader],
    WriteString[$Output, "The canonical Babelapha Mathematica notebook or its thin runtime loader was not found.\n"];
    Exit[12]
];

Get[runtimeLoader];
Global`$BabelaphaNotebookSourcePath = notebookPath;
If[BabelaphaNotebookEvaluateTag[notebookPath, "BabelaphaDefinitions"] === $Failed,
    WriteString[$Output, "The canonical notebook definitions could not be evaluated.\n"];
    Exit[12]
];

testSource = BabelaphaNotebookTaggedSource[notebookPath, "BabelaphaTests"];
If[testSource === $Failed,
    WriteString[$Output, "The embedded notebook tests could not be read.\n"];
    Exit[12]
];
testFile = FileNameJoin[{$TemporaryDirectory, "babelapha-notebook-tests-" <> CreateUUID[] <> ".wlt"}];
Export[testFile, testSource, "Text"];
report = TestReport[testFile];
Quiet[DeleteFile[testFile]];
succeeded = TrueQ[report["ReportSucceeded"]];
WriteString[
    $Output,
    ExportString[
        <|
            "status" -> If[succeeded, "SUCCEEDED", "FAILED"],
            "test_count" -> Length[report["Results"]],
            "test_file" -> "BabelaphaAnalysis.nb"
        |>,
        "RawJSON"
    ] <> "\n"
];
If[! succeeded, WriteString[$Output, ToString[report, OutputForm] <> "\n"]];
If[succeeded, Exit[0], Exit[1]]
