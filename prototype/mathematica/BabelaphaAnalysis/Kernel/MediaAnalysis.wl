PackageScoped[analyzeMedia]
PackageScoped[capability]

SetAttributes[safeMediaEvaluation, HoldFirst];
safeMediaEvaluation[expression_] := Quiet[Check[expression, $Failed]];

secondsMagnitude[value_?NumericQ] := N[value];
secondsMagnitude[value_Quantity] := N[QuantityMagnitude[UnitConvert[value, "Seconds"]]];
secondsMagnitude[_] := Null;

finiteNumberOrNull[value_] := If[finiteRealQ[value], N[value], Null];

intervalsToJSON[intervals_List, maximumDuration_] := Module[{converted},
    converted = Map[
        Function[interval,
            If[ListQ[interval] && Length[interval] == 2,
                Clip[secondsMagnitude /@ interval, {0., N[maximumDuration]}],
                Nothing
            ]
        ],
        intervals
    ];
    Select[converted, Last[#] > First[#] &]
];
intervalsToJSON[_, _] := {};

timeSeriesPairs[series_TimeSeries] := Module[{normal},
    normal = Normal[series];
    If[ListQ[normal] && AllTrue[normal, ListQ[#] && Length[#] == 2 &], normal, {}]
];

makeNamedMeasurementSeries[rmsSeries_TimeSeries, centroidSeries_TimeSeries] := Module[
    {rmsPairs, centroidPairs, count, times, values, series},
    rmsPairs = timeSeriesPairs[rmsSeries];
    centroidPairs = timeSeriesPairs[centroidSeries];
    count = Min[Length[rmsPairs], Length[centroidPairs]];
    ensureCondition[count > 0, AnalysisRuntimeException, "EMPTY_AUDIO_SERIES", "Audio local measurements produced no observations.", 20];
    times = rmsPairs[[;; count, 1]];
    values = Transpose[{rmsPairs[[;; count, 2]], centroidPairs[[;; count, 2]]}];
    series = safeMediaEvaluation[TimeSeries[values, {times}, {"rms_amplitude", "spectral_centroid_hz"}]];
    ensureCondition[Head[series] === TimeSeries, DependencyException, "NAMED_TIME_SERIES_UNAVAILABLE", "Named-component TimeSeries construction failed.", 12];
    series
];

summaryStatistics[values_List] := Module[{clean},
    clean = Select[Flatten[values], finiteRealQ];
    If[clean === {},
        <|"minimum" -> Null, "mean" -> Null, "maximum" -> Null|>,
        <|"minimum" -> N[Min[clean]], "mean" -> N[Mean[clean]], "maximum" -> N[Max[clean]]|>
    ]
];

columnKeyString[key_String] := key;
columnKeyString[key_Symbol] := SymbolName[Unevaluated[key]];
columnKeyString[key_] := ToString[key, InputForm];

frameMeanRGB[image_Image] := Module[{pixels},
    pixels = Flatten[ImageData[ColorConvert[image, "RGB"], "Real"], 1];
    N[Mean[pixels]]
];

frameBrightness[image_Image] := N[Mean[Flatten[ImageData[ColorConvert[image, "Grayscale"], "Real"]]]];

frameMotionValues[frames_List] := Module[{arrays},
    If[Length[frames] < 2, Return[{}]];
    arrays = ImageData[ColorConvert[#, "Grayscale"], "Real"] & /@ frames;
    MapThread[N[Mean[Abs[Flatten[#2 - #1]]]] &, {Most[arrays], Rest[arrays]}]
];

analyzeVideoFrames[video_Video, duration_] := Module[
    {frames, dimensions, brightness, rgb, rgbMean, motion, times, motionAligned, series},
    frames = safeMediaEvaluation[VideoFrameList[video, {"Uniform", 12}]];
    ensureCondition[ListQ[frames] && Length[frames] > 0 && AllTrue[frames, ImageQ], AnalysisRuntimeException, "VIDEO_FRAME_EXTRACTION_FAILED", "Uniform video frame extraction failed.", 20];
    dimensions = ImageDimensions[First[frames]];
    brightness = frameBrightness /@ frames;
    rgb = frameMeanRGB /@ frames;
    rgbMean = N[Mean[rgb]];
    motion = frameMotionValues[frames];
    times = If[Length[frames] == 1, {0.}, N[Subdivide[0., duration, Length[frames] - 1]]];
    motionAligned = Prepend[motion, 0.];
    series = safeMediaEvaluation[TimeSeries[Transpose[{brightness, motionAligned}], {times}, {"brightness", "frame_difference"}]];
    ensureCondition[Head[series] === TimeSeries, DependencyException, "VIDEO_TIME_SERIES_UNAVAILABLE", "Video named-component TimeSeries construction failed.", 12];
    <|
        "frames" -> frames,
        "time_series" -> series,
        "summary" -> <|
            "duration_seconds" -> N[duration],
            "frame_count_sampled" -> Length[frames],
            "frame_dimensions" -> dimensions,
            "brightness" -> summaryStatistics[brightness],
            "mean_rgb" -> <|"red" -> rgbMean[[1]], "green" -> rgbMean[[2]], "blue" -> rgbMean[[3]]|>,
            "motion" -> <|
                "method" -> "mean-absolute-grayscale-frame-difference",
                "transition_count" -> Length[motion],
                "mean" -> If[motion === {}, Null, N[Mean[motion]]],
                "maximum" -> If[motion === {}, Null, N[Max[motion]]]
            |>
        |>
    |>
];

emptyAudioAnalysis[] := <|
    "available" -> False,
    "audio" -> None,
    "rms_series" -> None,
    "centroid_series" -> None,
    "measurement_series" -> None,
    "summary" -> <|
        "duration_seconds" -> Null,
        "audio_duration_seconds" -> Null,
        "sample_rate_hz" -> Null,
        "channel_count" -> Null,
        "rms_amplitude" -> Null,
        "peak_amplitude" -> Null,
        "integrated_loudness_lufs" -> Null,
        "audible_intervals_seconds" -> {},
        "silence_intervals_seconds" -> {},
        "spectral_centroid_hz" -> <|"minimum" -> Null, "mean" -> Null, "maximum" -> Null|>,
        "measurement_series" -> <|"time_count" -> 0, "component_names" -> {}|>
    |>
|>;

analyzeAudioTrack[video_Video, parameters_Association, mediaDuration_] := Module[
    {audio, partition, rmsSeries, centroidSeries, namedSeries, thresholdAmplitude,
     audible, silence, centroidValues, audioDuration, summary},
    audio = safeMediaEvaluation[Audio[video]];
    If[! TrueQ[AudioQ[audio]], Return[emptyAudioAnalysis[]]];
    partition = {N[parameters["frame_seconds"]], N[parameters["hop_seconds"]]};
    rmsSeries = safeMediaEvaluation[AudioLocalMeasurements[audio, "RMSAmplitude", PartitionGranularity -> partition]];
    centroidSeries = safeMediaEvaluation[AudioLocalMeasurements[audio, "SpectralCentroid", PartitionGranularity -> partition]];
    ensureCondition[Head[rmsSeries] === TimeSeries && Head[centroidSeries] === TimeSeries, AnalysisRuntimeException, "AUDIO_LOCAL_MEASUREMENTS_FAILED", "AudioLocalMeasurements did not return TimeSeries values.", 20];
    namedSeries = makeNamedMeasurementSeries[rmsSeries, centroidSeries];
    thresholdAmplitude = 10.^N[parameters["silence_threshold_db"] / 20.];
    audible = safeMediaEvaluation[
        With[{threshold = thresholdAmplitude},
            AudioIntervals[audio, TrueQ[#RMSAmplitude > threshold] &, PartitionGranularity -> partition]
        ]
    ];
    silence = safeMediaEvaluation[
        With[{threshold = thresholdAmplitude},
            AudioIntervals[audio, TrueQ[#RMSAmplitude <= threshold] &, PartitionGranularity -> partition]
        ]
    ];
    ensureCondition[ListQ[audible] && ListQ[silence], AnalysisRuntimeException, "AUDIO_INTERVAL_DETECTION_FAILED", "AudioIntervals failed for the configured threshold.", 20];
    centroidValues = timeSeriesPairs[centroidSeries];
    centroidValues = If[centroidValues === {}, {}, centroidValues[[All, 2]]];
    audioDuration = secondsMagnitude[AudioMeasurements[audio, "Duration"]];
    summary = <|
        "duration_seconds" -> N[mediaDuration],
        "audio_duration_seconds" -> audioDuration,
        "sample_rate_hz" -> Round[AudioMeasurements[audio, "SampleRate"]],
        "channel_count" -> Round[AudioMeasurements[audio, "Channels"]],
        "rms_amplitude" -> finiteNumberOrNull[AudioMeasurements[audio, "RMSAmplitude"]],
        "peak_amplitude" -> finiteNumberOrNull[AudioMeasurements[audio, "MaxAbs"]],
        "integrated_loudness_lufs" -> finiteNumberOrNull[AudioMeasurements[audio, "LoudnessEBU"]],
        "audible_intervals_seconds" -> intervalsToJSON[audible, audioDuration],
        "silence_intervals_seconds" -> intervalsToJSON[silence, audioDuration],
        "spectral_centroid_hz" -> summaryStatistics[centroidValues],
        "measurement_series" -> <|
            "time_count" -> Length[Normal[namedSeries]],
            "component_names" -> DeleteCases[columnKeyString /@ ColumnKeys[namedSeries], "Timestamp"]
        |>
    |>;
    <|
        "available" -> True,
        "audio" -> audio,
        "rms_series" -> rmsSeries,
        "centroid_series" -> centroidSeries,
        "measurement_series" -> namedSeries,
        "summary" -> summary
    |>
];

capability[status_String, reason_String: ""] := <|"status" -> status, "reason" -> reason|>;

analyzeMedia[sourcePath_String, parameters_Association] := Module[
    {video, duration, frameAnalysis, audioAnalysis, capabilities},
    SeedRandom[parameters["random_seed"], Method -> "MersenneTwister"];
    video = safeMediaEvaluation[Video[sourcePath]];
    ensureCondition[TrueQ[VideoQ[video]], AnalysisRuntimeException, "VIDEO_IMPORT_FAILED", "Wolfram Video could not open the selected source.", 20, <|"Path" -> sourcePath|>];
    duration = secondsMagnitude[Duration[video]];
    ensureCondition[finiteRealQ[duration] && duration > 0., AnalysisRuntimeException, "INVALID_VIDEO_DURATION", "The video duration is missing or non-positive.", 20];
    frameAnalysis = analyzeVideoFrames[video, duration];
    audioAnalysis = analyzeAudioTrack[video, parameters, duration];
    capabilities = <|
        "video_import" -> capability["USED"],
        "audio_track" -> If[TrueQ[audioAnalysis["available"]], capability["USED"], capability["UNAVAILABLE", "The video has no decodable audio track."]],
        "video_summary_plot" -> capability["USED"],
        "frame_analysis" -> capability["USED"],
        "time_series" -> capability["USED"],
        "event_series" -> capability["USED"],
        "tabular" -> capability["USED"],
        "notebook_export" -> capability["USED"]
    |>;
    <|
        "video" -> video,
        "duration_seconds" -> duration,
        "frames" -> frameAnalysis["frames"],
        "video_time_series" -> frameAnalysis["time_series"],
        "video_summary" -> frameAnalysis["summary"],
        "audio_analysis" -> audioAnalysis,
        "capabilities" -> capabilities
    |>
];
