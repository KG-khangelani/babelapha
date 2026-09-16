#!/usr/bin/env wolframscript

testDirectory = DirectoryName[ExpandFileName[$InputFileName]];
packageLoader = FileNameJoin[{testDirectory, "..", "BabelaphaAnalysis", "Kernel", "init.wl"}];
testFile = FileNameJoin[{testDirectory, "BabelaphaAnalysisTests.wlt"}];

Get[packageLoader];
report = TestReport[testFile];
succeeded = TrueQ[report["ReportSucceeded"]];
WriteString[
    $Output,
    ExportString[
        <|
            "status" -> If[succeeded, "SUCCEEDED", "FAILED"],
            "test_count" -> Length[report["Results"]],
            "test_file" -> FileNameTake[testFile]
        |>,
        "RawJSON"
    ] <> "\n"
];
If[! succeeded, WriteString[$Output, ToString[report, OutputForm] <> "\n"]];
If[succeeded, Exit[0], Exit[1]]
