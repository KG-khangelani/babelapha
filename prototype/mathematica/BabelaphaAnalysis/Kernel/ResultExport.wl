PackageScoped[exportAnalysisArtifacts]
PackageScoped[writeRawResult]
PackageScoped[jsonSafe]

jsonSafe[value_] := Replace[
    value,
    {
        _Missing -> Null,
        Indeterminate -> Null,
        DirectedInfinity[_] -> Null,
        complex_Complex :> ToString[complex, InputForm]
    },
    {0, Infinity}
];

placeholderGraphic[title_String, reason_String] := Graphics[
    {
        GrayLevel[.97], Rectangle[{0, 0}, {1, 1}],
        GrayLevel[.2], Text[Style[title, 18, Bold], {.5, .62}],
        GrayLevel[.35], Text[Style[reason, 11], {.5, .40}]
    },
    PlotRange -> {{0, 1}, {0, 1}}, ImageSize -> 900
];

exportChecked[path_String, expression_, format_String] := Module[{result, deleted},
    If[FileExistsQ[path],
        deleted = Quiet[Check[DeleteFile[path]; ! FileExistsQ[path], False]];
        ensureCondition[deleted, ExportException, "STALE_ARTIFACT_DELETE_FAILED", "A previous Mathematica artifact could not be invalidated before export.", 20, <|"Path" -> path, "Format" -> format|>];
    ];
    result = Quiet[Check[
        If[format === "PNG",
            Export[path, expression, format, IncludeMetaInformation -> None],
            Export[path, expression, format]
        ],
        $Failed
    ]];
    ensureCondition[FileExistsQ[path] && FileByteCount[path] > 0, ExportException, "ARTIFACT_EXPORT_FAILED", "A required Mathematica artifact could not be exported.", 20, <|"Path" -> path, "Format" -> format|>];
    path
];

audioOverviewGraphic[audioAnalysis_Association] := Module[{audio, rms, centroid},
    If[! TrueQ[audioAnalysis["available"]],
        Return[placeholderGraphic["Audio overview", "No decodable audio track was found."]]
    ];
    audio = audioAnalysis["audio"];
    rms = audioAnalysis["rms_series"];
    centroid = audioAnalysis["centroid_series"];
    GraphicsColumn[
        {
            AudioPlot[audio, PlotLabel -> "Waveform", PlotLayout -> "Averaged", ImageSize -> 900],
            ListLinePlot[rms, PlotLabel -> "Local RMS amplitude", AxesLabel -> {"seconds", "RMS"}, PlotRange -> All, ImageSize -> 900],
            ListLinePlot[centroid, PlotLabel -> "Spectral centroid", AxesLabel -> {"seconds", "Hz"}, PlotRange -> All, ImageSize -> 900],
            Spectrogram[audio, PlotLabel -> "Spectrogram", ImageSize -> 900]
        },
        Spacings -> 12
    ]
];

audioVectorOverviewGraphic[audioAnalysis_Association] := Module[{rms, centroid},
    If[! TrueQ[audioAnalysis["available"]],
        Return[placeholderGraphic["Audio overview", "No decodable audio track was found."]]
    ];
    rms = audioAnalysis["rms_series"];
    centroid = audioAnalysis["centroid_series"];
    GraphicsColumn[
        {
            ListLinePlot[rms, PlotLabel -> "Local RMS amplitude", AxesLabel -> {"seconds", "RMS"}, PlotRange -> All, ImageSize -> 900],
            ListLinePlot[centroid, PlotLabel -> "Spectral centroid", AxesLabel -> {"seconds", "Hz"}, PlotRange -> All, ImageSize -> 900]
        },
        Spacings -> 12
    ]
];

contactSheetImage[frames_List] := Module[{columns, rows, blank, width, height},
    columns = Min[4, Length[frames]];
    {width, height} = ImageDimensions[First[frames]];
    blank = ConstantImage[GrayLevel[.12], {width, height}];
    rows = Partition[PadRight[frames, Ceiling[Length[frames]/columns] columns, blank], columns];
    ImageAssemble[rows]
];

summaryPlotWithFallback[media_Association] := Module[{plot},
    plot = Quiet[Check[VideoSummaryPlot[media["video"], "Row", MaxItems -> 12, ImageSize -> 1200], $Failed]];
    If[plot === $Failed,
        placeholderGraphic["VideoSummaryPlot unavailable", "The contact sheet contains the sampled frames."],
        plot
    ]
];

markdownReport[input_Association, measurements_Association, provenance_Association, capabilities_Association] := StringRiffle[
    {
        "# Babelapha local Mathematica media analysis",
        "",
        "- Analysis: `" <> input["analysis_id"] <> "`",
        "- Object: `" <> input["object_id"] <> "`",
        "- Run: `" <> input["run_id"] <> "`",
        "- Source: `" <> input["source", "path"] <> "`",
        "- Wolfram: `" <> $Version <> "`",
        "- Network mode: `disabled`",
        "",
        "## Portable measurements",
        "",
        "```json",
        ExportString[jsonSafe[measurements], "RawJSON"],
        "```",
        "",
        "## Provenance summary",
        "",
        "```json",
        ExportString[jsonSafe[provenance], "RawJSON"],
        "```",
        "",
        "## Mathematica capabilities exercised",
        "",
        "```json",
        ExportString[jsonSafe[capabilities], "RawJSON"],
        "```",
        "",
        "The raw JSON result must pass the independent Python boundary before it is canonical."
    },
    "\n"
];

htmlEscape[text_String] := StringReplace[text, {"&" -> "&amp;", "<" -> "&lt;", ">" -> "&gt;", "\"" -> "&quot;"}];

htmlReport[input_Association, measurements_Association, provenance_Association, capabilities_Association] := StringJoin[
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>Babelapha Mathematica analysis</title>",
    "<style>body{font:16px system-ui;margin:2rem;max-width:1100px}code,pre{font-family:ui-monospace,monospace}pre{background:#f4f5f7;padding:1rem;overflow:auto}img{max-width:100%;height:auto}</style></head><body>",
    "<h1>Babelapha local Mathematica media analysis</h1>",
    "<p><strong>Object:</strong> <code>", htmlEscape[input["object_id"]], "</code><br><strong>Run:</strong> <code>", htmlEscape[input["run_id"]], "</code><br><strong>Wolfram:</strong> <code>", htmlEscape[$Version], "</code><br><strong>Network:</strong> disabled</p>",
    "<h2>Video contact sheet</h2><img src=\"video-contact-sheet.png\" alt=\"Sampled video frames\">",
    "<h2>Video summary</h2><img src=\"video-summary.png\" alt=\"Video summary plot\">",
    "<h2>Audio analysis</h2><img src=\"audio-overview.png\" alt=\"Audio analysis plots\">",
    "<h2>Measurements</h2><pre>", htmlEscape[ExportString[jsonSafe[measurements], "RawJSON"]], "</pre>",
    "<h2>Provenance</h2><pre>", htmlEscape[ExportString[jsonSafe[provenance], "RawJSON"]], "</pre>",
    "<h2>Capabilities</h2><pre>", htmlEscape[ExportString[jsonSafe[capabilities], "RawJSON"]], "</pre>",
    "</body></html>"
];

analysisNotebook[input_Association, measurements_Association, provenance_Association, packageLoader_String, inputPath_String] := Module[{rerunCode},
    rerunCode = StringRiffle[
        {
            "package = " <> ToString[packageLoader, InputForm] <> ";",
            "Get[package];",
            "input = " <> ToString[inputPath, InputForm] <> ";",
            "BabelaphaAnalysis`RunAnalysisFile[input]"
        },
        "\n"
    ];
    Notebook[
        {
            Cell["Babelapha local Mathematica media analysis", "Title"],
            Cell["A portable review notebook generated by the same headless package used by the CLI.", "Text"],
            Cell["Identity", "Section"],
            Cell[BoxData[ToBoxes[Dataset[KeyTake[input, {"analysis_id", "object_id", "run_id", "source", "parameters"}]]]], "Output"],
            Cell["Measurements", "Section"],
            Cell[BoxData[ToBoxes[Dataset[measurements]]], "Output"],
            Cell["Provenance", "Section"],
            Cell[BoxData[ToBoxes[Dataset[provenance]]], "Output"],
            Cell["Re-run through the shared package", "Section"],
            Cell[rerunCode, "Input"]
        },
        WindowTitle -> "Babelapha Mathematica analysis"
    ]
];

outputRecord[path_String, mediaType_String] := <|
    "path" -> FileNameTake[path],
    "media_type" -> mediaType,
    "sha256" -> fileSHA256[path],
    "size_bytes" -> FileByteCount[path]
|>;

exportAnalysisArtifacts[input_Association, media_Association, measurements_Association, provenance_Association, outputDirectory_String, packageLoader_String, inputPath_String] := Module[
    {audioPNG, audioSVG, contactPNG, summaryPNG, markdownPath, htmlPath, notebookPath,
     audioGraphic, audioVectorGraphic, contact, summaryPlot, markdown, html, notebook, outputs, capabilities},
    If[! DirectoryQ[outputDirectory], CreateDirectory[outputDirectory, CreateIntermediateDirectories -> True]];
    audioPNG = FileNameJoin[{outputDirectory, "audio-overview.png"}];
    audioSVG = FileNameJoin[{outputDirectory, "audio-overview.svg"}];
    contactPNG = FileNameJoin[{outputDirectory, "video-contact-sheet.png"}];
    summaryPNG = FileNameJoin[{outputDirectory, "video-summary.png"}];
    markdownPath = FileNameJoin[{outputDirectory, "report.md"}];
    htmlPath = FileNameJoin[{outputDirectory, "report.html"}];
    notebookPath = FileNameJoin[{outputDirectory, "analysis-notebook.nb"}];
    capabilities = media["capabilities"];
    audioGraphic = audioOverviewGraphic[media["audio_analysis"]];
    exportChecked[audioPNG, audioGraphic, "PNG"];
    audioVectorGraphic = audioVectorOverviewGraphic[media["audio_analysis"]];
    exportChecked[audioSVG, audioVectorGraphic, "SVG"];
    contact = contactSheetImage[media["frames"]];
    exportChecked[contactPNG, contact, "PNG"];
    summaryPlot = summaryPlotWithFallback[media];
    If[MatchQ[summaryPlot, _Graphics] && ! FreeQ[summaryPlot, "VideoSummaryPlot unavailable"],
        capabilities["video_summary_plot"] = capability["UNAVAILABLE", "VideoSummaryPlot did not render; a diagnostic placeholder was exported."]
    ];
    exportChecked[summaryPNG, summaryPlot, "PNG"];
    markdown = markdownReport[input, measurements, provenance, capabilities];
    exportChecked[markdownPath, markdown, "Text"];
    html = htmlReport[input, measurements, provenance, capabilities];
    exportChecked[htmlPath, html, "Text"];
    notebook = analysisNotebook[input, measurements, provenance, packageLoader, inputPath];
    Quiet[Check[Put[notebook, notebookPath], throwAnalysisException[ExportException, "NOTEBOOK_EXPORT_FAILED", "The analysis notebook could not be written.", 20, <|"Path" -> notebookPath|>]]];
    ensureCondition[FileExistsQ[notebookPath] && FileByteCount[notebookPath] > 0, ExportException, "NOTEBOOK_EXPORT_FAILED", "The analysis notebook could not be written.", 20, <|"Path" -> notebookPath|>];
    outputs = {
        outputRecord[audioPNG, "image/png"],
        outputRecord[audioSVG, "image/svg+xml"],
        outputRecord[contactPNG, "image/png"],
        outputRecord[summaryPNG, "image/png"],
        outputRecord[markdownPath, "text/markdown"],
        outputRecord[htmlPath, "text/html"],
        outputRecord[notebookPath, "application/vnd.wolfram.mathematica"]
    };
    <|"outputs" -> outputs, "capabilities" -> capabilities|>
];

writeRawResult[result_Association, outputDirectory_String] := Module[{path, exported},
    path = FileNameJoin[{outputDirectory, "result.raw.json"}];
    exported = Check[Export[path, jsonSafe[result], "RawJSON"], $Failed];
    ensureCondition[exported =!= $Failed && FileExistsQ[path] && FileByteCount[path] > 0, ExportException, "RESULT_EXPORT_FAILED", "result.raw.json could not be exported.", 20, <|"Path" -> path|>];
    path
];
