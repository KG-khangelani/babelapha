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

notebookFiniteNumberQ[value_] := NumericQ[value] && FreeQ[value, Indeterminate | DirectedInfinity[_] | ComplexInfinity];

notebookLookup[value_, key_, default_] := If[AssociationQ[value], Lookup[value, key, default], default];

notebookNestedLookup[value_, keys_List, default_] := Fold[
    Function[{current, key}, notebookLookup[current, key, default]],
    value,
    keys
];

notebookLabel[key_] := StringReplace[Capitalize[ToString[key]], "_" -> " "];

notebookDisplayValue[Null | None | _Missing] := Style["Not available", Italic, GrayLevel[.45]];
notebookDisplayValue[value_?notebookFiniteNumberQ] := NumberForm[N[value], {10, 4}];
notebookDisplayValue[value_String] := Style[value, FontFamily -> "Consolas", FontSize -> 9];
notebookDisplayValue[value_] := Style[ToString[Short[value, 4], InputForm], FontFamily -> "Consolas", FontSize -> 8];

flattenNotebookAssociation[association_Association, prefix_String: ""] := Flatten[
    KeyValueMap[
        Function[{key, value},
            With[{label = If[prefix === "", notebookLabel[key], prefix <> " / " <> notebookLabel[key]]},
                If[AssociationQ[value], flattenNotebookAssociation[value, label], {{label, notebookDisplayValue[value]}}]
            ]
        ],
        association
    ],
    1
];
flattenNotebookAssociation[_, _String: ""] := {};

notebookCallout[text_String, tone_String: "info"] := If[
    tone === "good",
    Style[text, Bold],
    Style[text, Italic]
];

notebookTable[association_Association, emptyMessage_String: "No values were emitted for this section."] := Module[{rows},
    rows = flattenNotebookAssociation[association];
    If[rows === {},
        notebookCallout[emptyMessage, "absent"],
        Grid[
            Prepend[rows, {Style["Metric", Bold], Style["Value", Bold]}],
            Alignment -> {{Left, Left}, Center},
            Frame -> All,
            Spacings -> {1.1, .75}
        ]
    ]
];

notebookRecordsTable[records_List, emptyMessage_String] := Module[{associations, keys, rows},
    associations = Select[records, AssociationQ];
    If[associations === {}, Return[notebookCallout[emptyMessage, "absent"]]];
    keys = DeleteDuplicates[Flatten[Keys /@ associations]];
    rows = (notebookDisplayValue /@ Lookup[#, keys, Null]) & /@ associations;
    Grid[
        Prepend[rows, Style[notebookLabel[#], Bold] & /@ keys],
        Alignment -> Left,
        Frame -> All,
        Spacings -> {.8, .65}
    ]
];

notebookMetricCard[label_String, value_, note_String: ""] :=
    Column[
        DeleteCases[
            {
                Style[label, Bold],
                Style[value, 14],
                If[note === "", Nothing, note]
            },
            Nothing
        ],
        Spacings -> .25
    ];

notebookSeconds[value_] := If[
    notebookFiniteNumberQ[value],
    ToString[NumberForm[N[value], {Infinity, 2}]] <> " s",
    "Not available"
];

notebookHumanBytes[value_] := Which[
    ! NumericQ[value], "Not available",
    value >= 2^30, ToString[NumberForm[N[value/2^30], {Infinity, 2}]] <> " GiB",
    value >= 2^20, ToString[NumberForm[N[value/2^20], {Infinity, 2}]] <> " MiB",
    value >= 2^10, ToString[NumberForm[N[value/2^10], {Infinity, 1}]] <> " KiB",
    True, ToString[value] <> " bytes"
];

notebookShortHash[value_] := If[
    StringQ[value] && StringLength[value] > 24,
    StringTake[value, 12] <> "..." <> StringTake[value, -8],
    value
];

notebookCleanIntervals[value_] := Select[
    If[ListQ[value], value, {}],
    ListQ[#] && Length[#] == 2 && AllTrue[#, notebookFiniteNumberQ] && Last[#] >= First[#] &
];

notebookIntervalDuration[intervals_List] := Total[(Last[#] - First[#]) & /@ intervals];

notebookIntervalGraphic[audible_List, silence_List, duration_] := Module[{maximum},
    maximum = If[notebookFiniteNumberQ[duration] && duration > 0, N[duration], 1.];
    Graphics[
        {
            {RGBColor[.82, .84, .87], (Rectangle[{#[[1]], .05}, {#[[2]], .43}] &) /@ silence},
            {RGBColor[.16, .58, .78], (Rectangle[{#[[1]], .57}, {#[[2]], .95}] &) /@ audible},
            {GrayLevel[.25], Thickness[.001], Line[{{0., .5}, {maximum, .5}}]}
        },
        PlotRange -> {{0., maximum}, {0., 1.}},
        Frame -> True,
        FrameTicks -> {{{{.24, "Silence"}, {.76, "Audible"}}, None}, {Automatic, None}},
        FrameLabel -> {{None, None}, {"Time (seconds)", None}},
        ImagePadding -> {{62, 16}, {35, 8}},
        ImageSize -> 720,
        Background -> White
    ]
];

notebookFrameRGB[image_Image] := Module[{pixels},
    pixels = Flatten[ImageData[ColorConvert[image, "RGB"], "Real"], 1];
    N[Mean[pixels]]
];

notebookFrameBrightness[image_Image] := N[Mean[Flatten[ImageData[ColorConvert[image, "Grayscale"], "Real"]]]];

notebookMotionValues[frames_List] := Module[{arrays},
    If[Length[frames] < 2, Return[{}]];
    arrays = ImageData[ColorConvert[#, "Grayscale"], "Real"] & /@ frames;
    MapThread[N[Mean[Abs[Flatten[#2 - #1]]]] &, {Most[arrays], Rest[arrays]}]
];

notebookSampleTimes[media_Association, frameCount_Integer, duration_] := Module[{analytics, times},
    analytics = notebookLookup[media, "video_analytics", <||>];
    times = notebookLookup[analytics, "sample_times_seconds", {}];
    If[
        ListQ[times] && Length[times] == frameCount && AllTrue[times, notebookFiniteNumberQ],
        N[times],
        If[frameCount <= 1, {0.}, N[Subdivide[0., duration, frameCount - 1]]]
    ]
];

notebookStoryboard[frames_List, times_List] := Module[{tiles, columns},
    If[frames === {}, Return[notebookCallout["No video frames were available for the storyboard.", "warn"]]];
    tiles = MapThread[
        Function[{frame, time},
            Framed[
                Column[
                    {ImageResize[frame, 210], Style[notebookSeconds[time], 9, Bold, GrayLevel[.28]]},
                    Alignment -> Center,
                    Spacings -> .35
                ],
                Background -> White,
                FrameStyle -> GrayLevel[.82],
                FrameMargins -> 5
            ]
        ],
        {frames, times}
    ];
    columns = Min[3, Length[tiles]];
    Grid[
        Partition[PadRight[tiles, Ceiling[Length[tiles]/columns] columns, ""], columns],
        Alignment -> Top,
        Spacings -> {.7, .8}
    ]
];

notebookStoryboardPages[frames_List, times_List] := MapThread[
    notebookStoryboard,
    {
        Partition[frames, UpTo[3]],
        Partition[times, UpTo[3]]
    }
];

notebookColorVisual[frames_List, times_List, videoSummary_Association, videoAnalytics_Association] := Module[
    {rgbValues, meanRGB, colorAnalytics, palette, paletteColors, swatches, swatchRow, rgbPlot, brightnessValues, brightnessPlot},
    rgbValues = If[frames === {}, {}, notebookFrameRGB /@ frames];
    meanRGB = notebookLookup[videoSummary, "mean_rgb", <||>];
    meanRGB = If[
        AssociationQ[meanRGB],
        Lookup[meanRGB, {"red", "green", "blue"}, {0., 0., 0.}],
        If[rgbValues === {}, {0., 0., 0.}, Mean[rgbValues]]
    ];
    meanRGB = Clip[N[meanRGB], {0., 1.}];
    colorAnalytics = notebookLookup[videoAnalytics, "color", <||>];
    palette = notebookLookup[colorAnalytics, "palette", {}];
    paletteColors = DeleteMissing[
        Map[
            Function[value,
                Which[
                    MatchQ[value, _RGBColor], Take[List @@ value, 3],
                    AssociationQ[value] && AssociationQ[Lookup[value, "rgb", Null]], Lookup[Lookup[value, "rgb"], {"red", "green", "blue"}, Missing["NotAColor"]],
                    AssociationQ[value] && ListQ[Lookup[value, "rgb", Null]], Take[N[Lookup[value, "rgb"]], UpTo[3]],
                    ListQ[value] && Length[value] >= 3 && AllTrue[Take[value, 3], NumericQ], N[Take[value, 3]],
                    True, Missing["NotAColor"]
                ]
            ],
            If[ListQ[palette], palette, {}]
        ]
    ];
    If[paletteColors === {} && rgbValues =!= {}, paletteColors = Take[rgbValues, UpTo[8]]];
    swatches = (Graphics[{EdgeForm[GrayLevel[.70]], RGBColor @@ Clip[#, {0., 1.}], Rectangle[{0, 0}, {1, 1}]}, ImageSize -> {55, 38}] &) /@ paletteColors;
    swatchRow = Grid[
        {{
            Column[{Style["Mean sampled color", 9, Bold, GrayLevel[.30]], Graphics[{EdgeForm[GrayLevel[.55]], RGBColor @@ meanRGB, Rectangle[{0, 0}, {1, 1}]}, ImageSize -> {145, 82}]}],
            BarChart[meanRGB, ChartLabels -> Placed[{"R", "G", "B"}, Below], ChartStyle -> {RGBColor[.82, .18, .20], RGBColor[.15, .64, .32], RGBColor[.16, .40, .82]}, PlotRange -> {0, 1}, ImageSize -> {280, 145}],
            Column[{Style["Sampled palette", 9, Bold, GrayLevel[.30]], If[swatches === {}, Style["Not available", Italic], Grid[Partition[PadRight[swatches, Ceiling[Length[swatches]/4] 4, ""], 4], Spacings -> .2]]}]
        }},
        Alignment -> Top,
        Spacings -> 1.3
    ];
    rgbPlot = If[
        rgbValues === {},
        Nothing,
        ListLinePlot[
            Table[Transpose[{times, rgbValues[[All, index]]}], {index, 3}],
            PlotStyle -> {RGBColor[.82, .18, .20], RGBColor[.15, .64, .32], RGBColor[.16, .40, .82]},
            PlotLegends -> Placed[{"Red", "Green", "Blue"}, Below],
            Frame -> True,
            Axes -> False,
            FrameLabel -> {"Time (seconds)", "Mean channel intensity"},
            PlotRange -> {0, 1},
            ImageSize -> 720,
            GridLines -> Automatic
        ]
    ];
    brightnessValues = If[frames === {}, {}, notebookFrameBrightness /@ frames];
    brightnessPlot = If[
        brightnessValues === {},
        Nothing,
        ListLinePlot[
            Transpose[{times, brightnessValues}],
            PlotStyle -> Directive[RGBColor[.94, .56, .15], Thick],
            Filling -> Axis,
            FillingStyle -> Directive[RGBColor[1., .78, .35], Opacity[.25]],
            Frame -> True,
            Axes -> False,
            FrameLabel -> {"Time (seconds)", "Perceived brightness"},
            PlotRange -> {0, 1},
            ImageSize -> 720,
            GridLines -> Automatic
        ]
    ];
    Column[DeleteCases[{swatchRow, rgbPlot, brightnessPlot}, Nothing], Spacings -> 1.2]
];

notebookCandidateTime[candidate_] := Which[
    notebookFiniteNumberQ[candidate], N[candidate],
    AssociationQ[candidate], SelectFirst[Lookup[candidate, {"time_seconds", "timestamp_seconds", "time"}, Null], notebookFiniteNumberQ, Missing["NoTime"]],
    True, Missing["NoTime"]
];

notebookMotionVisual[frames_List, times_List, sceneCandidates_List] := Module[{motion, motionTimes, sceneTimes},
    motion = notebookMotionValues[frames];
    motionTimes = If[Length[times] >= 2, Rest[times], {}];
    sceneTimes = DeleteMissing[notebookCandidateTime /@ sceneCandidates];
    If[
        motion === {},
        notebookCallout["At least two sampled frames are required for temporal motion analysis.", "warn"],
        ListLinePlot[
            Transpose[{motionTimes, motion}],
            PlotStyle -> Directive[RGBColor[.47, .25, .72], Thick],
            Filling -> Axis,
            FillingStyle -> Directive[RGBColor[.58, .40, .78], Opacity[.22]],
            Epilog -> (({RGBColor[.88, .30, .20], Dashed, Thick, Line[{{#, 0}, {#, Max[Append[motion, .001]]}}]} &) /@ sceneTimes),
            Frame -> True,
            FrameStyle -> GrayLevel[.16],
            Axes -> False,
            Background -> White,
            FrameLabel -> {"Time (seconds)", "Mean frame difference"},
            PlotRange -> All,
            ImageSize -> 720,
            GridLines -> Automatic
        ]
    ]
];

notebookTranscriptData[media_Association, measurements_Association] := Module[{candidate},
    candidate = notebookLookup[media, "transcript", Null];
    If[! AssociationQ[candidate], candidate = notebookLookup[measurements, "transcript", <||>]];
    If[AssociationQ[candidate], candidate, <||>]
];

notebookTranscriptSegments[transcript_Association] := Module[{segments},
    segments = notebookLookup[transcript, "segments", {}];
    If[ListQ[segments], Select[segments, AssociationQ], {}]
];

notebookSegmentBounds[segment_Association] := Module[{start, finish},
    start = SelectFirst[Lookup[segment, {"start_seconds", "start", "begin_seconds"}, Null], notebookFiniteNumberQ, Missing["NoStart"]];
    finish = SelectFirst[Lookup[segment, {"end_seconds", "end", "finish_seconds"}, Null], notebookFiniteNumberQ, Missing["NoEnd"]];
    If[notebookFiniteNumberQ[start] && notebookFiniteNumberQ[finish] && finish >= start, {N[start], N[finish]}, Missing["NoBounds"]]
];

notebookSeriesPairs[series_] := Module[{normal},
    normal = Quiet[Check[Normal[series], {}]];
    Select[
        If[ListQ[normal], normal, {}],
        ListQ[#] && Length[#] == 2 && notebookFiniteNumberQ[First[#]] && notebookFiniteNumberQ[Last[#]] &
    ]
];

notebookAudioAnalyticsSummary[analytics_Association] := <|
    "analysis_status" -> notebookLookup[analytics, "status", Null],
    "method" -> notebookLookup[analytics, "method", Null],
    "crest_factor" -> notebookNestedLookup[analytics, {"dynamics", "crest_factor"}, Null],
    "crest_factor_db" -> notebookNestedLookup[analytics, {"dynamics", "crest_factor_db"}, Null],
    "local_dynamic_range_db" -> notebookNestedLookup[analytics, {"dynamics", "local_dynamic_range_db"}, Null],
    "rms_dbfs_mean" -> notebookNestedLookup[analytics, {"dynamics", "rms_dbfs", "mean"}, Null],
    "rms_dbfs_q05" -> notebookNestedLookup[analytics, {"dynamics", "rms_dbfs", "q05"}, Null],
    "rms_dbfs_q95" -> notebookNestedLookup[analytics, {"dynamics", "rms_dbfs", "q95"}, Null],
    "local_loudness_mean" -> notebookNestedLookup[analytics, {"dynamics", "local_loudness", "mean"}, Null],
    "local_loudness_q05" -> notebookNestedLookup[analytics, {"dynamics", "local_loudness", "q05"}, Null],
    "local_loudness_q95" -> notebookNestedLookup[analytics, {"dynamics", "local_loudness", "q95"}, Null],
    "spectral_centroid_mean_hz" -> notebookNestedLookup[analytics, {"frequency", "spectral_centroid_hz", "mean"}, Null],
    "spectral_centroid_q95_hz" -> notebookNestedLookup[analytics, {"frequency", "spectral_centroid_hz", "q95"}, Null],
    "spectral_spread_mean_hz" -> notebookNestedLookup[analytics, {"frequency", "spectral_spread_hz", "mean"}, Null],
    "zero_crossing_rate_mean" -> notebookNestedLookup[analytics, {"frequency", "zero_crossing_rate", "mean"}, Null],
    "nyquist_hz" -> notebookNestedLookup[analytics, {"frequency", "nyquist_frequency_hz"}, Null],
    "pitch_status" -> notebookNestedLookup[analytics, {"pitch", "status"}, Null],
    "pitch_method" -> notebookNestedLookup[analytics, {"pitch", "method"}, Null],
    "pitch_coverage" -> notebookNestedLookup[analytics, {"pitch", "coverage_fraction"}, Null],
    "pitch_mean_hz" -> notebookNestedLookup[analytics, {"pitch", "fundamental_frequency_hz", "mean"}, Null],
    "pitch_median_hz" -> notebookNestedLookup[analytics, {"pitch", "fundamental_frequency_hz", "median"}, Null]
|>;

notebookAudioDiagnosticPlots[audioAnalysis_Association] := Module[{specifications, plots},
    specifications = {
        {"peak_series", "Local peak amplitude", "Amplitude", RGBColor[.84, .30, .24]},
        {"loudness_series", "Local loudness", "dB", RGBColor[.16, .60, .36]},
        {"spectral_spread_series", "Spectral spread", "Hz", RGBColor[.22, .48, .76]},
        {"zero_crossing_rate_series", "Zero-crossing rate", "Rate", RGBColor[.55, .34, .72]},
        {"pitch_series", "Fundamental-frequency candidates", "Hz", RGBColor[.90, .55, .12]}
    };
    plots = DeleteCases[
        Map[
            Function[specification,
                With[{series = notebookLookup[audioAnalysis, specification[[1]], None]},
                    If[
                        notebookSeriesPairs[series] === {},
                        Nothing,
                        ListLinePlot[
                            series,
                            PlotLabel -> Style[specification[[2]], 9, Bold, GrayLevel[.12]],
                            PlotStyle -> Directive[specification[[4]], Thick],
                            Frame -> True,
                            FrameStyle -> GrayLevel[.18],
                            FrameTicksStyle -> GrayLevel[.22],
                            LabelStyle -> Directive[GrayLevel[.15], 8],
                            Axes -> False,
                            Background -> White,
                            FrameLabel -> {"Seconds", specification[[3]]},
                            PlotRange -> All,
                            ImageSize -> {315, 150},
                            GridLines -> Automatic
                        ]
                    ]
                ]
            ],
            specifications
        ],
        Nothing
    ];
    If[
        plots === {},
        notebookCallout["No extended audio time-series plots were emitted by this engine run.", "absent"],
        Grid[
            Partition[
                PadRight[plots, Ceiling[Length[plots]/2] 2, Graphics[{}, PlotRange -> {{0, 1}, {0, 1}}, Background -> White, ImageSize -> {315, 150}]],
                2
            ],
            Alignment -> Top,
            Spacings -> {.6, .8}
        ]
    ]
];

notebookAudioOverviewPanel[audioAnalysis_Association] := Module[{audio, rms, centroid, panel},
    If[
        ! TrueQ[notebookLookup[audioAnalysis, "available", False]],
        Return[notebookCallout["No decodable audio track was found, so waveform and spectral diagnostics are unavailable.", "absent"]]
    ];
    audio = notebookLookup[audioAnalysis, "audio", None];
    rms = notebookLookup[audioAnalysis, "rms_series", None];
    centroid = notebookLookup[audioAnalysis, "centroid_series", None];
    panel = Grid[
        {
            {
                AudioPlot[audio, PlotLabel -> Style["Waveform", 9, Bold, GrayLevel[.12]], PlotLayout -> "Averaged", AxesStyle -> GrayLevel[.18], TicksStyle -> GrayLevel[.22], LabelStyle -> Directive[GrayLevel[.15], 8], ImageSize -> {315, 150}],
                ListLinePlot[rms, PlotLabel -> Style["Local RMS amplitude", 9, Bold, GrayLevel[.12]], Frame -> True, FrameStyle -> GrayLevel[.18], FrameTicksStyle -> GrayLevel[.22], LabelStyle -> Directive[GrayLevel[.15], 8], Axes -> False, FrameLabel -> {"Seconds", "RMS"}, PlotRange -> All, ImageSize -> {315, 150}]
            },
            {
                ListLinePlot[centroid, PlotLabel -> Style["Spectral centroid", 9, Bold, GrayLevel[.12]], Frame -> True, FrameStyle -> GrayLevel[.18], FrameTicksStyle -> GrayLevel[.22], LabelStyle -> Directive[GrayLevel[.15], 8], Axes -> False, FrameLabel -> {"Seconds", "Hz"}, PlotRange -> All, ImageSize -> {315, 150}],
                Spectrogram[audio, PlotLabel -> Style["Spectrogram", 9, Bold, GrayLevel[.12]], AxesStyle -> GrayLevel[.18], TicksStyle -> GrayLevel[.22], LabelStyle -> Directive[GrayLevel[.15], 8], ImageSize -> {315, 150}]
            }
        },
        Alignment -> Top,
        Spacings -> {.55, .65}
    ];
    panel
];

notebookNormalizedLine[pairs_List, laneBottom_] := Module[{values, minimum, maximum, normalized},
    If[pairs === {}, Return[{}]];
    values = N[pairs[[All, 2]]];
    minimum = Min[values];
    maximum = Max[values];
    normalized = If[maximum > minimum, (values - minimum)/(maximum - minimum), ConstantArray[.5, Length[values]]];
    Line[Transpose[{N[pairs[[All, 1]]], laneBottom + .10 + .62 normalized}]]
];

notebookArtifactInventory[outputDirectory_String] := Module[{specifications},
    specifications = {
        {"video-contact-sheet.png", "image/png", "Uniform frame storyboard"},
        {"video-summary.png", "image/png", "Wolfram VideoSummaryPlot"},
        {"audio-overview.png", "image/png", "Waveform and spectral diagnostics"},
        {"audio-overview.svg", "image/svg+xml", "Portable vector audio diagnostics"},
        {"report.md", "text/markdown", "Portable machine-readable review report"},
        {"report.html", "text/html", "Browser review report"},
        {"analysis-notebook.nb", "application/vnd.wolfram.mathematica", "This interactive review notebook"}
    };
    Map[
        Function[specification,
            Module[{path = FileNameJoin[{outputDirectory, specification[[1]]}], exists},
                exists = FileExistsQ[path] && specification[[1]] =!= "analysis-notebook.nb";
                <|
                    "artifact" -> specification[[1]],
                    "media_type" -> specification[[2]],
                    "role" -> specification[[3]],
                    "status" -> If[exists, "EXPORTED", If[specification[[1]] === "analysis-notebook.nb", "THIS DOCUMENT", "PENDING"]],
                    "size_bytes" -> If[exists, FileByteCount[path], Null],
                    "sha256" -> If[exists, notebookShortHash[fileSHA256[path]], "Recorded after notebook export"]
                |>
            ]
        ],
        specifications
    ]
];

notebookCrossModalGraphic[duration_, audible_List, silence_List, brightnessPairs_List, rmsPairs_List, loudnessPairs_List, motionPairs_List, transcriptSegments_List, sceneCandidates_List] := Module[
    {maximum, brightnessLine, rmsLine, loudnessLine, motionLine, transcriptBounds, sceneTimes},
    maximum = If[notebookFiniteNumberQ[duration] && duration > 0, N[duration], 1.];
    brightnessLine = notebookNormalizedLine[brightnessPairs, 2.];
    rmsLine = notebookNormalizedLine[rmsPairs, 3.];
    loudnessLine = notebookNormalizedLine[loudnessPairs, 4.];
    motionLine = notebookNormalizedLine[motionPairs, 5.];
    transcriptBounds = DeleteMissing[notebookSegmentBounds /@ transcriptSegments];
    sceneTimes = DeleteMissing[notebookCandidateTime /@ sceneCandidates];
    Graphics[
        {
            {RGBColor[.84, .85, .87], (Rectangle[{#[[1]], .05}, {#[[2]], .70}] &) /@ silence},
            {RGBColor[.16, .58, .78], (Rectangle[{#[[1]], 1.05}, {#[[2]], 1.70}] &) /@ audible},
            {Directive[RGBColor[.94, .56, .15], Thick], brightnessLine},
            {Directive[RGBColor[.12, .55, .72], Thick], rmsLine},
            {Directive[RGBColor[.15, .64, .32], Thick], loudnessLine},
            {Directive[RGBColor[.47, .25, .72], Thick], motionLine},
            {RGBColor[.20, .65, .42], Opacity[.60], (Rectangle[{#[[1]], 6.05}, {#[[2]], 6.70}] &) /@ transcriptBounds},
            {Directive[RGBColor[.88, .30, .20], Dashed, Thick], (Line[{{#, 0.}, {#, 6.8}}] &) /@ sceneTimes}
        },
        PlotRange -> {{0., maximum}, {0., 6.85}},
        Frame -> True,
        FrameTicks -> {{{{.38, "Silence"}, {1.38, "Audible"}, {2.40, "Brightness"}, {3.40, "RMS level"}, {4.40, "Loudness"}, {5.40, "Motion"}, {6.38, "Transcript"}}, None}, {Automatic, None}},
        FrameLabel -> {{None, None}, {"Shared media time (seconds)", None}},
        ImagePadding -> {{78, 16}, {36, 8}},
        ImageSize -> 720,
        Background -> White
    ]
];

notebookFrameExplorer[frames_List, times_List] := Module[
    {count, rgbValues, brightnessValues},
    count = Length[frames];
    If[count == 0 || Length[times] =!= count,
        Return[Style["No sampled frames are available for interactive exploration.", Italic]]
    ];
    rgbValues = notebookFrameRGB /@ frames;
    brightnessValues = notebookFrameBrightness /@ frames;
    With[
        {
            storedFrames = ExportByteArray[ImageResize[#, 480], "JPEG"] & /@ frames,
            storedTimes = N[times],
            storedRGB = N[rgbValues],
            storedBrightness = N[brightnessValues],
            frameCount = count
        },
        DynamicModule[
            {index = 1},
            Column[
                {
                    Row[
                        {
                            "Sampled frame ", Dynamic[Round[index]], " of ", frameCount,
                            Spacer[15],
                            Animator[Dynamic[index], {1, frameCount, 1}, AnimationRate -> 1]
                        }
                    ],
                    Slider[Dynamic[index], {1, frameCount, 1}, ImageSize -> Large],
                    Dynamic[
                        With[{current = Clip[Round[index], {1, frameCount}]},
                            Column[
                                {
                                    ImportByteArray[storedFrames[[current]], "JPEG"],
                                    Grid[
                                        {
                                            {"Time (seconds)", NumberForm[storedTimes[[current]], {Infinity, 3}]},
                                            {"Mean RGB", NumberForm[storedRGB[[current]], {4, 3}]},
                                            {"Brightness", NumberForm[storedBrightness[[current]], {4, 3}]},
                                            {"Mean color", Graphics[{RGBColor @@ Clip[storedRGB[[current]], {0., 1.}], Rectangle[]}, ImageSize -> {120, 24}]}
                                        },
                                        Alignment -> Left
                                    ]
                                },
                                Alignment -> Center
                            ]
                        ],
                        TrackedSymbols :> {index}
                    ]
                }
            ]
        ]
    ]
];

notebookAudioExplorer[audioAnalysis_Association, duration_] := Module[
    {specifications, maximum},
    If[! TrueQ[notebookLookup[audioAnalysis, "available", False]],
        Return[Style["No decodable audio track is available for interactive playback.", Italic]]
    ];
    specifications = Select[
        {
            {"RMS amplitude", notebookSeriesPairs[notebookLookup[audioAnalysis, "rms_series", None]]},
            {"Peak amplitude", notebookSeriesPairs[notebookLookup[audioAnalysis, "peak_series", None]]},
            {"Loudness", notebookSeriesPairs[notebookLookup[audioAnalysis, "loudness_series", None]]},
            {"Spectral centroid", notebookSeriesPairs[notebookLookup[audioAnalysis, "centroid_series", None]]},
            {"Spectral spread", notebookSeriesPairs[notebookLookup[audioAnalysis, "spectral_spread_series", None]]},
            {"Zero-crossing rate", notebookSeriesPairs[notebookLookup[audioAnalysis, "zero_crossing_rate_series", None]]},
            {"Fundamental frequency", notebookSeriesPairs[notebookLookup[audioAnalysis, "pitch_series", None]]}
        },
        Last[#] =!= {} &
    ];
    If[specifications === {}, Return[Style["No timestamped audio measurements are available for exploration.", Italic]]];
    maximum = If[
        notebookFiniteNumberQ[duration] && duration > 0,
        N[duration],
        Max[Flatten[(Last[#][[All, 1]] &) /@ specifications]]
    ];
    With[
        {
            storedSeries = Association[Rule @@@ specifications],
            metricNames = First /@ specifications,
            mediaDuration = maximum
        },
        DynamicModule[
            {metric = First[metricNames], cursor = 0.},
            Column[
                {
                    Row[{"Metric: ", PopupMenu[Dynamic[metric], metricNames]}],
                    Row[{"Time: ", Dynamic[NumberForm[cursor, {Infinity, 2}]], " s"}],
                    Slider[Dynamic[cursor], {0., mediaDuration}, ImageSize -> Large],
                    Dynamic[
                        With[
                            {
                                pairs = storedSeries[metric],
                                selected = First@MinimalBy[storedSeries[metric], Abs[First[#] - cursor] &]
                            },
                            With[
                                {
                                    range = If[Min[pairs[[All, 2]]] == Max[pairs[[All, 2]]], Min[pairs[[All, 2]]] + {-0.5, 0.5}, MinMax[pairs[[All, 2]]]]
                                },
                                Column[
                                    {
                                        ListLinePlot[
                                            pairs,
                                            Frame -> True,
                                            Axes -> False,
                                            FrameLabel -> {"Time (seconds)", metric},
                                            PlotRange -> All,
                                            Epilog -> {Red, Dashed, Line[{{cursor, First[range]}, {cursor, Last[range]}}], PointSize[Medium], Point[selected]},
                                            ImageSize -> Large
                                        ],
                                        Row[{"Nearest measurement: ", NumberForm[Last[selected], {Infinity, 4}], " at ", NumberForm[First[selected], {Infinity, 3}], " s"}]
                                    }
                                ]
                            ]
                        ],
                        TrackedSymbols :> {metric, cursor}
                    ]
                }
            ]
        ]
    ]
];

notebookTranscriptExplorer[transcript_Association] := Module[
    {segments, labels, count},
    segments = notebookTranscriptSegments[transcript];
    If[segments === {},
        Return[Style["No timestamped transcript segments are available for navigation.", Italic]]
    ];
    count = Length[segments];
    labels = MapIndexed[(First[#2] -> ("Segment " <> ToString[First[#2]])) &, segments];
    With[
        {
            storedSegments = segments,
            menuLabels = labels,
            segmentCount = count
        },
        DynamicModule[
            {index = 1, query = ""},
            Column[
                {
                    Row[{"Transcript segment: ", PopupMenu[Dynamic[index], menuLabels]}],
                    If[segmentCount > 1, Slider[Dynamic[index], {1, segmentCount, 1}, ImageSize -> Large], Nothing],
                    Row[{"Search transcript: ", InputField[Dynamic[query], String]}],
                    Dynamic[
                        With[
                            {
                                segment = storedSegments[[Clip[Round[index], {1, segmentCount}]]],
                                bounds = Lookup[storedSegments[[Clip[Round[index], {1, segmentCount}]]], {"start_seconds", "end_seconds"}, {0., 0.}]
                            },
                            Column[
                                DeleteCases[
                                    {
                                        Grid[
                                            {
                                                {"Start (seconds)", NumberForm[First[bounds], {Infinity, 3}]},
                                                {"End (seconds)", NumberForm[Last[bounds], {Infinity, 3}]}
                                            },
                                            Alignment -> Left
                                        ],
                                        Style[Lookup[segment, "text", ""], "Text"]
                                    },
                                    Nothing
                                ]
                            ]
                        ],
                        TrackedSymbols :> {index}
                    ],
                    Dynamic[
                        If[
                            StringTrim[query] === "",
                            Nothing,
                            With[
                                {matches = Select[storedSegments, StringContainsQ[ToString[Lookup[#, "text", ""]], query, IgnoreCase -> True] &]},
                                If[matches === {}, Style["No transcript segments match the search.", Italic], Column[Lookup[matches, "text", {}]]]
                            ]
                        ],
                        TrackedSymbols :> {query}
                    ]
                }
            ]
        ]
    ]
];

notebookTimelineExplorer[graphic_, duration_, transcriptSegments_List] := Module[
    {maximum, transcriptRecords},
    maximum = If[notebookFiniteNumberQ[duration] && duration > 0, N[duration], 1.];
    transcriptRecords = DeleteMissing@Map[
        Function[segment,
            With[{bounds = notebookSegmentBounds[segment]},
                If[
                    MissingQ[bounds],
                    Missing["NoBounds"],
                    <|"start" -> First[bounds], "end" -> Last[bounds], "text" -> notebookLookup[segment, "text", "" ]|>
                ]
            ]
        ],
        transcriptSegments
    ];
    With[
        {storedGraphic = graphic, mediaDuration = maximum, storedTranscript = transcriptRecords},
        DynamicModule[
            {cursor = 0.},
            Column[
                {
                    Row[{"Media time: ", Dynamic[NumberForm[cursor, {Infinity, 2}]], " s"}],
                    Slider[Dynamic[cursor], {0., mediaDuration}, ImageSize -> Large],
                    Dynamic[
                        Show[
                            storedGraphic,
                            Graphics[{Red, Thick, Line[{{cursor, 0.}, {cursor, 6.85}}]}]
                        ],
                        TrackedSymbols :> {cursor}
                    ],
                    Dynamic[
                        With[
                            {active = SelectFirst[storedTranscript, #["start"] <= cursor <= #["end"] &, Missing["NoTranscript"]]},
                            If[MissingQ[active], Style["No transcript segment covers this time.", Italic], Style[active["text"], "Text"]]
                        ],
                        TrackedSymbols :> {cursor}
                    ]
                }
            ]
        ]
    ]
];

notebookCapabilityTable[capabilities_Association] := Module[{rows},
    rows = KeyValueMap[
        Function[{name, detail},
            With[{status = notebookLookup[detail, "status", "UNKNOWN"]},
                {
                    notebookLabel[name],
                    Style[status, Bold, Switch[status, "USED", RGBColor[.12, .53, .28], "UNAVAILABLE", RGBColor[.70, .39, .08], _, GrayLevel[.35]]],
                    notebookLookup[detail, "reason", ""]
                }
            ]
        ],
        capabilities
    ];
    Grid[
        Prepend[rows, Style[#, Bold] & /@ {"Capability", "Status", "Reason / scope"}],
        Alignment -> Left,
        Frame -> All,
        Spacings -> {.8, .7}
    ]
];

analysisNotebook[input_Association, media_Association, measurements_Association, provenance_Association, capabilities_Association, visuals_Association, outputDirectory_String, packageLoader_String, inputPath_String] := Module[
    {setupCode, setupHeld, rerunCode, rerunHeld, workspaceRoot, sourceAbsolutePath,
     source, videoSummary, videoAnalytics, frames, duration, times, rgbMean,
     audioAnalysis, audioSummary, audioAvailable, audible, silence, audibleShare,
     sceneChanges, sceneCandidates, transcript, transcriptSegments, transcriptStatus,
     transcriptContent, transcriptReason, transcriptMethod, transcriptMode, transcriptSource,
     transcriptStatistics, transcriptDetails, motion, motionTimes, brightnessPairs, rmsPairs, loudnessPairs, motionPairs,
     sourceRuntime, overviewCards, storyboardPages, colorDetails,
     motionDetails, audioAnalytics, audioAnalyticsSummary, provenanceDetails, eventSummary, parameters,
     methodologyItems, artifactInventory, crossModal, transcriptNotice, transcriptTextBlock,
     videoPlayer, frameExplorer, audioExplorer, transcriptExplorer, timelineExplorer, cells},
    workspaceRoot = DirectoryName[DirectoryName[ExpandFileName[inputPath]]];
    source = notebookLookup[input, "source", <||>];
    sourceAbsolutePath = FileNameJoin[{workspaceRoot, StringReplace[ToString[notebookLookup[source, "path", ""]], "/" -> $PathnameSeparator]}];
    setupCode = StringRiffle[
        {
            "babelaphaNotebookRoot = ExpandFileName[FileNameJoin[{NotebookDirectory[], \"..\"}]];",
            "babelaphaSourcePath = FileNameJoin[{babelaphaNotebookRoot, \"ingest\", " <> ToString[notebookLookup[source, "filename", ""], InputForm] <> "}];",
            "babelaphaAnalysisInputPath = FileNameJoin[{babelaphaNotebookRoot, \"artefacts\", \"analysis-input.json\"}];",
            "babelaphaResultPath = FileNameJoin[{NotebookDirectory[], \"result.json\"}];",
            "babelaphaResult := Import[babelaphaResultPath, \"RawJSON\"];"
        },
        "\n"
    ];
    setupHeld = ToExpression[setupCode, InputForm, Defer];
    rerunCode = StringRiffle[
        {
            "package = FileNameJoin[{DirectoryName[babelaphaNotebookRoot], \"prototype\", \"mathematica\", \"BabelaphaAnalysis\", \"Kernel\", \"init.wl\"}];",
            "Get[package];",
            "BabelaphaAnalysis`RunAnalysisFile[babelaphaAnalysisInputPath]"
        },
        "\n"
    ];
    rerunHeld = ToExpression[rerunCode, InputForm, Defer];
    videoSummary = notebookLookup[measurements, "video", notebookLookup[media, "video_summary", <||>]];
    videoAnalytics = notebookLookup[media, "video_analytics", <||>];
    frames = notebookLookup[media, "frames", {}];
    If[! ListQ[frames], frames = {}];
    duration = notebookLookup[measurements, "duration_seconds", notebookLookup[media, "duration_seconds", Null]];
    times = notebookSampleTimes[media, Length[frames], duration];
    storyboardPages = {
        If[
            KeyExistsQ[visuals, "video_contact_sheet"],
            ImageResize[visuals["video_contact_sheet"], 720],
            notebookStoryboard[ImageResize[#, 320] & /@ frames, times]
        ]
    };
    rgbMean = notebookLookup[videoSummary, "mean_rgb", <||>];
    audioAnalysis = notebookLookup[media, "audio_analysis", <||>];
    audioSummary = notebookLookup[audioAnalysis, "summary", <||>];
    audioAvailable = TrueQ[notebookLookup[audioAnalysis, "available", False]];
    audible = notebookCleanIntervals[notebookLookup[audioSummary, "audible_intervals_seconds", {}]];
    silence = notebookCleanIntervals[notebookLookup[audioSummary, "silence_intervals_seconds", {}]];
    audibleShare = If[
        notebookFiniteNumberQ[duration] && duration > 0,
        Clip[notebookIntervalDuration[audible]/duration, {0., 1.}],
        Null
    ];
    sceneChanges = notebookLookup[videoAnalytics, "scene_changes", <||>];
    sceneCandidates = notebookLookup[sceneChanges, "candidates", {}];
    If[! ListQ[sceneCandidates], sceneCandidates = {}];
    transcript = notebookTranscriptData[media, measurements];
    transcriptSegments = notebookTranscriptSegments[transcript];
    transcriptStatus = ToUpperCase[ToString[notebookLookup[transcript, "status", "UNAVAILABLE"]]];
    transcriptContent = notebookLookup[transcript, "text", ""];
    transcriptReason = ToString[notebookLookup[transcript, "reason", ""]];
    transcriptMethod = ToString[notebookLookup[transcript, "method", "unknown"]];
    transcriptMode = ToString[notebookNestedLookup[input, {"transcript", "mode"}, "unknown"]];
    transcriptSource = Switch[
        transcriptMethod,
        "wolfram_whisper_v1_tiny", "local Wolfram Whisper-V1 Tiny inference",
        "sidecar", "verified local transcript sidecar",
        "disabled", "disabled by configuration",
        _, transcriptMethod
    ];
    transcriptStatistics = notebookLookup[transcript, "statistics", <||>];
    transcriptDetails = Join[
        <|
            "status" -> transcriptStatus,
            "requested_mode" -> transcriptMode,
            "method" -> transcriptMethod,
            "source" -> transcriptSource,
            "reason" -> If[transcriptReason === "", "None; transcript analysis succeeded.", transcriptReason],
            "segment_count" -> Length[transcriptSegments],
            "model_status" -> notebookNestedLookup[transcript, {"model", "status"}, Null],
            "model_resource" -> notebookNestedLookup[transcript, {"model", "repository_resource_name"}, Null],
            "model_version" -> notebookNestedLookup[transcript, {"model", "resource_version"}, Null],
            "model_size" -> notebookNestedLookup[transcript, {"model", "size"}, Null],
            "target_device" -> notebookNestedLookup[transcript, {"inference", "target_device"}, Null],
            "network_mode" -> notebookNestedLookup[transcript, {"inference", "network_mode"}, Null]
        |>,
        If[AssociationQ[transcriptStatistics], transcriptStatistics, <||>]
    ];
    motion = notebookMotionValues[frames];
    motionTimes = If[Length[times] >= 2, Rest[times], {}];
    sourceRuntime = <|
        "analysis_id" -> notebookLookup[input, "analysis_id", Null],
        "object_id" -> notebookLookup[input, "object_id", Null],
        "run_id" -> notebookLookup[input, "run_id", Null],
        "source_path" -> notebookLookup[source, "path", Null],
        "source_size" -> notebookHumanBytes[notebookLookup[source, "size_bytes", Null]],
        "source_sha256" -> notebookShortHash[notebookLookup[source, "sha256", Null]],
        "wolfram_version" -> $Version,
        "system_id" -> $SystemID,
        "package_sha256" -> notebookShortHash[notebookLookup[input, "package_sha256", Null]],
        "network_mode" -> "disabled"
    |>;
    overviewCards = {
        notebookMetricCard["Duration", notebookSeconds[duration], "Video timeline"],
        notebookMetricCard["Sampled frames", ToString[Length[frames]], ToString[notebookLookup[videoSummary, "frame_dimensions", "?"]] <> " pixels"],
        notebookMetricCard["Audio", If[audioAvailable, "Available", "Unavailable"], If[audioAvailable, ToString[notebookLookup[audioSummary, "channel_count", "?"]] <> " channel(s)", "No decodable track"]],
        notebookMetricCard[
            "Loudness",
            If[notebookFiniteNumberQ[notebookLookup[audioSummary, "integrated_loudness_lufs", Null]], ToString[NumberForm[notebookLookup[audioSummary, "integrated_loudness_lufs", Null], {Infinity, 2}]] <> " LUFS", "Not available"],
            "Integrated EBU"
        ],
        notebookMetricCard["Audible share", If[notebookFiniteNumberQ[audibleShare], ToString[NumberForm[100. audibleShare, {Infinity, 1}]] <> "%", "Not available"], ToString[Length[audible]] <> " interval(s)"],
        notebookMetricCard["Transcript", transcriptStatus, If[transcriptStatus === "AVAILABLE", transcriptSource, If[transcriptReason === "", "No transcript text", transcriptReason]]]
    };
    colorDetails = Join[
        <|"mean_rgb" -> rgbMean, "brightness" -> notebookLookup[videoSummary, "brightness", Null]|>,
        If[
            AssociationQ[notebookLookup[videoAnalytics, "color", <||>]],
            KeyDrop[notebookLookup[videoAnalytics, "color", <||>], {"palette", "mean_rgb", "per_frame"}],
            <||>
        ]
    ];
    motionDetails = Join[
        <|"motion" -> notebookLookup[videoSummary, "motion", Null]|>,
        If[AssociationQ[sceneChanges], KeyDrop[sceneChanges, {"candidates"}], <||>]
    ];
    audioAnalytics = notebookLookup[audioAnalysis, "analytics", <||>];
    audioAnalyticsSummary = If[AssociationQ[audioAnalytics], notebookAudioAnalyticsSummary[audioAnalytics], <||>];
    brightnessPairs = If[frames === {}, {}, Transpose[{times, notebookFrameBrightness /@ frames}]];
    rmsPairs = notebookSeriesPairs[notebookLookup[audioAnalysis, "rms_series", None]];
    loudnessPairs = notebookSeriesPairs[
        notebookLookup[
            audioAnalysis,
            "loudness_series",
            notebookNestedLookup[audioAnalysis, {"analytics", "dynamics", "loudness_series"}, None]
        ]
    ];
    motionPairs = If[motion === {} || motionTimes === {}, {}, Transpose[{motionTimes, motion}]];
    provenanceDetails = Join[
        provenance,
        <|
            "evidence_path" -> notebookNestedLookup[input, {"evidence", "path"}, Null],
            "evidence_input_sha256" -> notebookShortHash[notebookNestedLookup[input, {"evidence", "sha256"}, Null]]
        |>
    ];
    eventSummary = notebookLookup[measurements, "evidence_events", <||>];
    parameters = notebookLookup[input, "parameters", <||>];
    methodologyItems = {
        "Video is decoded locally by Wolfram Language; uniformly sampled frames feed storyboard, RGB, brightness, and frame-difference views.",
        "Color values are normalized RGB measurements. Motion is the mean absolute grayscale difference between adjacent sampled frames; it is a screening signal, not optical flow.",
        "Sound analysis uses AudioLocalMeasurements and AudioIntervals with the configured frame, hop, and silence-threshold parameters; the overview embeds waveform, RMS, spectral centroid, and spectrogram views.",
        "Transcript content is shown only when supplied by a verified analysis or timestamped sidecar. Missing speech text is reported explicitly and is never synthesized.",
        "The run executes with Wolfram internet access disabled. Source, evidence, package, and emitted artifacts are bound by SHA-256 at the Python trust boundary."
    };
    artifactInventory = notebookArtifactInventory[outputDirectory];
    crossModal = notebookCrossModalGraphic[duration, audible, silence, brightnessPairs, rmsPairs, loudnessPairs, motionPairs, transcriptSegments, sceneCandidates];
    transcriptNotice = If[
        transcriptStatus === "AVAILABLE",
        Style["Available — produced by " <> transcriptSource <> ".", Bold],
        Column[{Style[transcriptStatus, Bold], If[transcriptReason === "", "No reason was emitted.", transcriptReason]}]
    ];
    transcriptTextBlock = If[
        StringQ[transcriptContent] && StringLength[StringTrim[transcriptContent]] > 0,
        Style[transcriptContent, "Text"],
        Style["No transcript body is attached. " <> transcriptReason, Italic]
    ];
    videoPlayer = If[FileExistsQ[sourceAbsolutePath], Video[sourceAbsolutePath, ImageSize -> Large], Style["The local source video could not be found at " <> sourceAbsolutePath, Italic]];
    frameExplorer = notebookFrameExplorer[frames, times];
    audioExplorer = notebookAudioExplorer[audioAnalysis, duration];
    transcriptExplorer = notebookTranscriptExplorer[transcript];
    timelineExplorer = notebookTimelineExplorer[crossModal, duration, transcriptSegments];
    cells = {
        Cell["Babelapha media intelligence notebook", "Title"],
        Cell["A local, inspectable Mathematica analysis surface — generated from the same package used by the headless runner.", "Subtitle"],

        Cell[CellGroupData[{
            Cell["Executive overview", "Section"],
            Cell["A concise readout of what this run could verify. Every detailed section below remains tied to the source and evidence hashes.", "Text"],
            Cell[BoxData[ToBoxes[Grid[{Take[overviewCards, 3]}, Alignment -> Top, Spacings -> {.55, 0}]]], "Output"],
            Cell[BoxData[ToBoxes[Grid[{Drop[overviewCards, 3]}, Alignment -> Top, Spacings -> {.55, 0}]]], "Output"]
        }, Open]],

        Cell[CellGroupData[{
            Cell["Source and runtime", "Section"],
            Cell["Identity, runtime, and integrity anchors for this exact local execution.", "Text"],
            Cell[BoxData[ToBoxes[notebookTable[sourceRuntime]]], "Output"],
            Cell["Analysis parameters", "Subsection"],
            Cell[BoxData[ToBoxes[notebookTable[parameters]]], "Output"],
            Cell["Editable notebook setup", "Subsection"],
            Cell["This initialization cell resolves the local workspace, source, input, and canonical result relative to the notebook. Mathematica will offer to evaluate it when a dependent input cell is run.", "Text"],
            Cell[BoxData[ToBoxes[setupHeld]], "Input", InitializationCell -> True]
        }, Open]],

        Cell[CellGroupData[Join[
            {
                Cell["Video storyboard", "Section"],
                Cell["Live source video", "Subsection"],
                Cell[BoxData[ToBoxes[videoPlayer]], "Output"],
                Cell["Interactive sampled-frame explorer", "Subsection"],
                Cell[BoxData[ToBoxes[frameExplorer]], "Output"],
                Cell["Uniformly sampled frames provide a visual index across the complete source duration. Timestamps use the shared media clock. The storyboard is split into print-safe groups so every sampled frame remains visible.", "Text"]
            },
            Cell[BoxData[ToBoxes[#]], "Output"] & /@ storyboardPages,
            {
                Cell["Wolfram video summary", "Subsection"],
                Cell[BoxData[ToBoxes[notebookLookup[visuals, "video_summary", notebookCallout["VideoSummaryPlot was unavailable for this run.", "warn"]]]], "Output"]
            }
        ], Open]],

        Cell[CellGroupData[{
            Cell["Color analysis", "Section"],
            Cell["Mean color, sampled palette, RGB trajectories, and perceived brightness reveal grading, fades, and large visual transitions.", "Text"],
            Cell[BoxData[ToBoxes[notebookColorVisual[frames, times, videoSummary, videoAnalytics]]], "Output"],
            Cell["Color measurements", "Subsection"],
            Cell[BoxData[ToBoxes[notebookTable[colorDetails]]], "Output"]
        }, Open]],

        Cell[CellGroupData[{
            Cell["Motion and temporal structure", "Section"],
            Cell["Frame-to-frame change is plotted on the common time axis. Dashed red markers identify emitted scene-change candidates when available.", "Text"],
            Cell[BoxData[ToBoxes[notebookMotionVisual[frames, times, sceneCandidates]]], "Output"],
            Cell[BoxData[ToBoxes[notebookTable[motionDetails]]], "Output"],
            Cell["Scene-change candidates", "Subsection"],
            Cell[BoxData[ToBoxes[notebookRecordsTable[sceneCandidates, "No scene-change candidates were emitted for this source at the configured threshold."]]], "Output"]
        }, Open]],

        Cell[CellGroupData[{
            Cell["Sound intelligence", "Section"],
            Cell[
                If[audioAvailable,
                    "The embedded diagnostic panel combines waveform, local RMS amplitude, spectral centroid, and a spectrogram. Metrics and interval bands remain numeric and auditable.",
                    "No decodable audio track was found. The notebook records that absence instead of displaying fabricated sound metrics."
                ],
                "Text"
            ],
            Cell["Interactive playback and measurement explorer", "Subsection"],
            Cell[BoxData[ToBoxes[audioExplorer]], "Output"],
            Cell[BoxData[ToBoxes[notebookLookup[visuals, "audio_overview", notebookCallout["No audio overview was produced.", "absent"]]]], "Output"],
            Cell["Sound measurements", "Subsection"],
            Cell[BoxData[ToBoxes[notebookTable[KeyDrop[audioSummary, {"audible_intervals_seconds", "silence_intervals_seconds", "measurement_series"}]]]], "Output"],
            Cell["Audible and silent intervals", "Subsection"],
            Cell[BoxData[ToBoxes[If[audioAvailable, notebookIntervalGraphic[audible, silence, notebookLookup[audioSummary, "audio_duration_seconds", duration]], notebookCallout["Interval analysis is unavailable because this source has no decodable audio track.", "absent"]]]], "Output"],
            Cell["Extended audio diagnostic curves", "Subsection"],
            Cell[BoxData[ToBoxes[If[AssociationQ[audioAnalytics] && audioAnalytics =!= <||>, notebookAudioDiagnosticPlots[audioAnalysis], notebookCallout["No additional pitch, dynamics, distribution, or frequency diagnostics were emitted by this engine run.", "absent"]]]], "Output"],
            Cell["Selected extended audio metrics", "Subsection"],
            Cell[BoxData[ToBoxes[If[AssociationQ[audioAnalytics] && audioAnalytics =!= <||>, notebookTable[audioAnalyticsSummary], notebookCallout["No extended audio metrics were emitted by this engine run.", "absent"]]]], "Output"]
        }, Open]],

        Cell[CellGroupData[{
            Cell["Transcript and speech text", "Section"],
            Cell[BoxData[ToBoxes[transcriptNotice]], "Output"],
            Cell["Transcript diagnostics", "Subsection"],
            Cell[BoxData[ToBoxes[notebookTable[transcriptDetails]]], "Output"],
            Cell[BoxData[ToBoxes[transcriptTextBlock]], "Output"],
            Cell["Interactive segment navigator", "Subsection"],
            Cell[BoxData[ToBoxes[transcriptExplorer]], "Output"],
            Cell["Timestamped segments", "Subsection"],
            Cell[BoxData[ToBoxes[notebookRecordsTable[transcriptSegments, "No timestamped transcript segments are attached to this run."]]], "Output"]
        }, Open]],

        Cell[CellGroupData[{
            Cell["Cross-modal timeline", "Section"],
            Cell["Audio activity, normalized RMS and loudness, sampled brightness, motion intensity, scene-change markers, and transcript coverage share one media-time axis. Empty lanes are evidence of unavailable data, not zero-valued measurements.", "Text"],
            Cell[BoxData[ToBoxes[crossModal]], "Output"],
            Cell["Interactive time cursor", "Subsection"],
            Cell[BoxData[ToBoxes[timelineExplorer]], "Output"]
        }, Open]],

        Cell[CellGroupData[{
            Cell["Provenance and evidence", "Section"],
            Cell["These records make the notebook traceable to its local source, source-evidence document, and execution identity.", "Text"],
            Cell[BoxData[ToBoxes[notebookTable[provenanceDetails]]], "Output"],
            Cell["Evidence event summary", "Subsection"],
            Cell[BoxData[ToBoxes[notebookTable[eventSummary]]], "Output"],
            Cell["Output inventory", "Subsection"],
            Cell["The notebook hash is necessarily recorded only after this document is written; all earlier artifacts are hashed before notebook construction.", "Text"],
            Cell[BoxData[ToBoxes[notebookRecordsTable[artifactInventory, "No output artifacts were found."]]], "Output"]
        }, Open]],

        Cell[CellGroupData[Join[
            {
                Cell["Capabilities and methodology", "Section"],
                Cell[BoxData[ToBoxes[notebookCapabilityTable[capabilities]]], "Output"]
            },
            Cell[#, "Item"] & /@ methodologyItems
        ], Open]],

        Cell[CellGroupData[{
            Cell["Re-run through the verified package", "Section"],
            Cell["The notebook is a review surface. This input cell invokes the same package entry point as the headless local runner; it does not contain a second analysis implementation.", "Text"],
            Cell[BoxData[ToBoxes[rerunHeld]], "Input"]
        }, Open]]
    };
    Notebook[
        cells,
        WindowTitle -> "Babelapha media intelligence — " <> ToString[notebookLookup[input, "object_id", "local analysis"]],
        WindowSize -> {1260, 900},
        WindowMargins -> {{Automatic, 20}, {Automatic, 20}},
        StyleDefinitions -> "Default.nb",
        TaggingRules -> <|
            "analysis_id" -> notebookLookup[input, "analysis_id", Null],
            "object_id" -> notebookLookup[input, "object_id", Null],
            "run_id" -> notebookLookup[input, "run_id", Null]
        |>
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
     audioGraphic, audioVectorGraphic, contact, summaryPlot, markdown, html, notebook, outputs, capabilities, visuals},
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
    visuals = <|
        "audio_overview" -> notebookAudioOverviewPanel[media["audio_analysis"]],
        "video_contact_sheet" -> contact,
        "video_summary" -> ImageResize[Import[summaryPNG], 720]
    |>;
    notebook = analysisNotebook[input, media, measurements, provenance, capabilities, visuals, outputDirectory, packageLoader, inputPath];
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
