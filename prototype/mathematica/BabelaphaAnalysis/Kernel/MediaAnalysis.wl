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

distributionStatistics[values_List] := Module[{clean, quantiles},
    clean = Select[Flatten[values], finiteRealQ];
    If[clean === {},
        Return[<|
            "count" -> 0,
            "minimum" -> Null,
            "q05" -> Null,
            "q25" -> Null,
            "median" -> Null,
            "q75" -> Null,
            "q95" -> Null,
            "maximum" -> Null,
            "mean" -> Null,
            "standard_deviation" -> Null
        |>]
    ];
    quantiles = N[Quantile[clean, {.05, .25, .5, .75, .95}]];
    <|
        "count" -> Length[clean],
        "minimum" -> N[Min[clean]],
        "q05" -> quantiles[[1]],
        "q25" -> quantiles[[2]],
        "median" -> quantiles[[3]],
        "q75" -> quantiles[[4]],
        "q95" -> quantiles[[5]],
        "maximum" -> N[Max[clean]],
        "mean" -> N[Mean[clean]],
        "standard_deviation" -> If[Length[clean] > 1, N[StandardDeviation[clean]], 0.]
    |>
];

histogramSummary[values_List, binCount_Integer: 12] := Module[
    {clean, range, edges, counts, total, histogram},
    clean = Select[Flatten[values], finiteRealQ];
    If[clean === {}, Return[<|"bin_edges" -> {}, "counts" -> {}, "fractions" -> {}|>]];
    range = MinMax[clean];
    If[First[range] == Last[range],
        Return[<|
            "bin_edges" -> N[{First[range], Last[range]}],
            "counts" -> {Length[clean]},
            "fractions" -> {1.}
        |>]
    ];
    histogram = HistogramList[clean, binCount];
    edges = N[First[histogram]];
    counts = Last[histogram];
    total = Total[counts];
    <|
        "bin_edges" -> edges,
        "counts" -> counts,
        "fractions" -> If[total > 0, N[counts/total], ConstantArray[0., Length[counts]]]
    |>
];

amplitudeDBFS[value_?NumericQ] := N[20. Log10[Max[Abs[N[value]], 10.^-12]]];

seriesValues[series_TimeSeries] := Module[{pairs},
    pairs = timeSeriesPairs[series];
    If[pairs === {}, {}, Select[pairs[[All, 2]], finiteRealQ]]
];
seriesValues[_] := {};

safeLocalMeasurement[audio_Audio, property_String, partition_] := Module[{series},
    series = safeMediaEvaluation[AudioLocalMeasurements[audio, property, PartitionGranularity -> partition]];
    If[Head[series] === TimeSeries, series, None]
];

featureAvailability[series_, unavailableReason_String] := Module[{count},
    count = Length[seriesValues[series]];
    If[count > 0,
        <|"status" -> "AVAILABLE", "observation_count" -> count, "reason" -> ""|>,
        <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> unavailableReason|>
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

analysisFramePixels[image_Image] := Flatten[
    ImageData[ColorConvert[ImageResize[image, 96], "RGB"], "Real"],
    1
];

rgbSaturation[pixel_List] := Module[{minimum, maximum},
    minimum = Min[pixel];
    maximum = Max[pixel];
    If[maximum <= 0., 0., N[(maximum - minimum)/maximum]]
];

rgbHex[rgb_List] := "#" <> StringJoin[
    ToUpperCase[IntegerString[Round[255 Clip[#, {0., 1.}]], 16, 2]] & /@ rgb
];

frameColorMetrics[image_Image] := Module[
    {pixels, gray, meanRGB, saturation, rg, yb, colorfulness},
    pixels = analysisFramePixels[image];
    gray = Flatten[ImageData[ColorConvert[ImageResize[image, 96], "Grayscale"], "Real"]];
    meanRGB = N[Mean[pixels]];
    saturation = rgbSaturation /@ pixels;
    rg = pixels[[All, 1]] - pixels[[All, 2]];
    yb = (pixels[[All, 1]] + pixels[[All, 2]])/2. - pixels[[All, 3]];
    colorfulness = Sqrt[
        If[Length[rg] > 1, Variance[rg], 0.] + If[Length[yb] > 1, Variance[yb], 0.]
    ] + .3 Sqrt[Mean[rg]^2 + Mean[yb]^2];
    <|
        "brightness" -> N[Mean[gray]],
        "saturation" -> N[Mean[saturation]],
        "contrast" -> If[Length[gray] > 1, N[StandardDeviation[gray]], 0.],
        "colorfulness" -> N[colorfulness],
        "mean_rgb_values" -> meanRGB,
        "mean_rgb" -> <|"red" -> meanRGB[[1]], "green" -> meanRGB[[2]], "blue" -> meanRGB[[3]]|>,
        "mean_color_hex" -> rgbHex[meanRGB]
    |>
];

colorBinIndex[pixel_List] := Module[{quantized},
    quantized = Floor[4 Clip[N[pixel], {0., 1. - 10.^-12}]];
    16 quantized[[1]] + 4 quantized[[2]] + quantized[[3]]
];

normalizedColorHistogram[pixels_List] := Module[{indices, counts, total},
    indices = colorBinIndex /@ pixels;
    counts = (Count[indices, #] &) /@ Range[0, 63];
    total = Total[counts];
    If[total > 0, N[counts/total], ConstantArray[0., 64]]
];

dominantColorPalette[framePixels_List, paletteSize_Integer: 8] := Module[
    {pixels, groups, ordered, total},
    pixels = Join @@ framePixels;
    If[pixels === {}, Return[{}]];
    groups = GatherBy[pixels, colorBinIndex];
    ordered = SortBy[groups, Function[group, {-Length[group], rgbHex[N[Mean[group]]]}]];
    total = Length[pixels];
    MapIndexed[
        Function[{group, index},
            With[{mean = N[Mean[group]]},
                <|
                    "rank" -> First[index],
                    "hex" -> rgbHex[mean],
                    "rgb" -> <|"red" -> mean[[1]], "green" -> mean[[2]], "blue" -> mean[[3]]|>,
                    "fraction" -> N[Length[group]/total]
                |>
            ]
        ],
        Take[ordered, UpTo[paletteSize]]
    ]
];

sceneChangeAnalysis[times_List, motion_List, histogramDistances_List] := Module[
    {scores, median, deviation, threshold, candidates},
    If[motion === {} || histogramDistances === {},
        Return[<|
            "method" -> "sampled-frame grayscale motion and 4x4x4 RGB histogram distance",
            "threshold" -> Null,
            "candidates" -> {}
        |>]
    ];
    scores = N[(Clip[4. motion, {0., 1.}] + histogramDistances)/2.];
    median = Median[scores];
    deviation = Median[Abs[scores - median]];
    threshold = N[Max[.12, median + 2.5 deviation]];
    candidates = Map[
        Function[index,
            <|
                "from_sample_index" -> index,
                "to_sample_index" -> index + 1,
                "time_seconds" -> N[times[[index + 1]]],
                "score" -> scores[[index]],
                "frame_difference" -> N[motion[[index]]],
                "color_histogram_distance" -> N[histogramDistances[[index]]]
            |>
        ],
        Flatten[Position[scores, value_ /; value >= threshold]]
    ];
    <|
        "method" -> "sampled-frame grayscale motion and 4x4x4 RGB histogram distance",
        "threshold" -> threshold,
        "candidates" -> candidates
    |>
];

frameMotionValues[frames_List] := Module[{arrays},
    If[Length[frames] < 2, Return[{}]];
    arrays = ImageData[ColorConvert[#, "Grayscale"], "Real"] & /@ frames;
    MapThread[N[Mean[Abs[Flatten[#2 - #1]]]] &, {Most[arrays], Rest[arrays]}]
];

analyzeVideoFrames[video_Video, duration_] := Module[
    {frames, dimensions, brightness, rgb, rgbMean, motion, times, motionAligned, series,
     colorMetrics, framePixels, saturations, contrasts, colorfulness, histograms,
     histogramDistances, histogramDistanceAligned, analyticsSeries, perFrame, palette,
     sceneChanges, analytics},
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
    colorMetrics = frameColorMetrics /@ frames;
    framePixels = analysisFramePixels /@ frames;
    saturations = Lookup[colorMetrics, "saturation"];
    contrasts = Lookup[colorMetrics, "contrast"];
    colorfulness = Lookup[colorMetrics, "colorfulness"];
    histograms = normalizedColorHistogram /@ framePixels;
    histogramDistances = If[
        Length[histograms] < 2,
        {},
        MapThread[N[Total[Abs[#2 - #1]]/2.] &, {Most[histograms], Rest[histograms]}]
    ];
    histogramDistanceAligned = Prepend[histogramDistances, 0.];
    analyticsSeries = safeMediaEvaluation[
        TimeSeries[
            Transpose[{brightness, saturations, contrasts, colorfulness, motionAligned, histogramDistanceAligned}],
            {times},
            {"brightness", "saturation", "contrast", "colorfulness", "frame_difference", "color_histogram_distance"}
        ]
    ];
    ensureCondition[Head[analyticsSeries] === TimeSeries, DependencyException, "VIDEO_ANALYTICS_TIME_SERIES_UNAVAILABLE", "Video analytics TimeSeries construction failed.", 12];
    perFrame = MapThread[
        Function[{index, time, metrics, frameDifference, histogramDistance},
            Join[
                <|
                    "sample_index" -> index,
                    "time_seconds" -> N[time],
                    "frame_difference" -> N[frameDifference],
                    "color_histogram_distance" -> N[histogramDistance]
                |>,
                KeyDrop[metrics, {"mean_rgb_values"}]
            ]
        ],
        {Range[Length[frames]], times, colorMetrics, motionAligned, histogramDistanceAligned}
    ];
    palette = dominantColorPalette[framePixels];
    sceneChanges = sceneChangeAnalysis[times, motion, histogramDistances];
    analytics = <|
        "sample_times_seconds" -> times,
        "time_series" -> analyticsSeries,
        "per_frame" -> perFrame,
        "color" -> <|
            "method" -> "uniform sampled frames resized to 96 pixels wide; deterministic 4x4x4 RGB quantization",
            "mean_rgb" -> <|"red" -> rgbMean[[1]], "green" -> rgbMean[[2]], "blue" -> rgbMean[[3]]|>,
            "palette" -> palette,
            "brightness" -> distributionStatistics[brightness],
            "saturation" -> distributionStatistics[saturations],
            "contrast" -> distributionStatistics[contrasts],
            "colorfulness" -> distributionStatistics[colorfulness]
        |>,
        "scene_changes" -> sceneChanges
    |>;
    <|
        "frames" -> frames,
        "time_series" -> series,
        "analytics" -> analytics,
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
    "peak_series" -> None,
    "spectral_spread_series" -> None,
    "zero_crossing_rate_series" -> None,
    "loudness_series" -> None,
    "pitch_series" -> None,
    "measurement_series" -> None,
    "analytics" -> <|
        "status" -> "UNAVAILABLE",
        "reason" -> "The video has no decodable audio track.",
        "method" -> "Wolfram AudioLocalMeasurements over configured overlapping windows",
        "dynamics" -> <||>,
        "distribution" -> <||>,
        "frequency" -> <||>,
        "pitch" -> <|
            "status" -> "UNAVAILABLE",
            "reason" -> "The video has no decodable audio track.",
            "method" -> "AudioLocalMeasurements/FundamentalFrequency",
            "observation_count" -> 0,
            "window_count" -> 0,
            "coverage_fraction" -> 0.,
            "fundamental_frequency_hz" -> distributionStatistics[{}]
        |>,
        "availability" -> <|
            "rms_amplitude" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>,
            "peak_amplitude" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>,
            "spectral_centroid" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>,
            "spectral_spread" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>,
            "zero_crossing_rate" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>,
            "local_loudness" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>,
            "fundamental_frequency" -> <|"status" -> "UNAVAILABLE", "observation_count" -> 0, "reason" -> "No audio track."|>
        |>
    |>,
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
     audible, silence, centroidValues, audioDuration, summary, peakSeries, spreadSeries,
     zeroCrossingSeries, loudnessSeries, pitchSeries, rmsValues, peakValues, spreadValues,
     zeroCrossingValues, loudnessValues, pitchValues, rmsDBFSValues, nonSilentRMSDBFS,
     globalRMS, globalPeak, audioSamples, crestFactor, crestFactorDB, localDynamicRangeDB, pitchStatus,
     pitchReason, windowCount, sampleRate, analytics},
    audio = safeMediaEvaluation[Audio[video]];
    If[! TrueQ[AudioQ[audio]], Return[emptyAudioAnalysis[]]];
    partition = {N[parameters["frame_seconds"]], N[parameters["hop_seconds"]]};
    rmsSeries = safeMediaEvaluation[AudioLocalMeasurements[audio, "RMSAmplitude", PartitionGranularity -> partition]];
    centroidSeries = safeMediaEvaluation[AudioLocalMeasurements[audio, "SpectralCentroid", PartitionGranularity -> partition]];
    ensureCondition[Head[rmsSeries] === TimeSeries && Head[centroidSeries] === TimeSeries, AnalysisRuntimeException, "AUDIO_LOCAL_MEASUREMENTS_FAILED", "AudioLocalMeasurements did not return TimeSeries values.", 20];
    peakSeries = safeLocalMeasurement[audio, "MaxAbs", partition];
    spreadSeries = safeLocalMeasurement[audio, "SpectralSpread", partition];
    zeroCrossingSeries = safeLocalMeasurement[audio, "ZeroCrossingRate", partition];
    loudnessSeries = safeLocalMeasurement[audio, "Loudness", partition];
    pitchSeries = safeLocalMeasurement[audio, "FundamentalFrequency", partition];
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
    rmsValues = seriesValues[rmsSeries];
    peakValues = seriesValues[peakSeries];
    spreadValues = seriesValues[spreadSeries];
    zeroCrossingValues = seriesValues[zeroCrossingSeries];
    loudnessValues = seriesValues[loudnessSeries];
    pitchValues = seriesValues[pitchSeries];
    rmsDBFSValues = amplitudeDBFS /@ rmsValues;
    nonSilentRMSDBFS = amplitudeDBFS /@ Select[rmsValues, # > 10.^-12 &];
    globalRMS = finiteNumberOrNull[AudioMeasurements[audio, "RMSAmplitude"]];
    globalPeak = finiteNumberOrNull[AudioMeasurements[audio, "MaxAbs"]];
    If[! finiteRealQ[globalRMS] || ! finiteRealQ[globalPeak],
        audioSamples = Select[
            Flatten@N@safeMediaEvaluation[AudioData[audio]],
            finiteRealQ
        ];
        If[audioSamples =!= {},
            If[! finiteRealQ[globalRMS], globalRMS = N[Sqrt[Mean[audioSamples^2]]]];
            If[! finiteRealQ[globalPeak], globalPeak = N[Max[Abs[audioSamples]]]]
        ]
    ];
    If[! finiteRealQ[globalRMS] && rmsValues =!= {}, globalRMS = N[Sqrt[Mean[rmsValues^2]]]];
    If[! finiteRealQ[globalPeak] && peakValues =!= {}, globalPeak = N[Max[peakValues]]];
    crestFactor = If[
        finiteRealQ[globalRMS] && finiteRealQ[globalPeak] && globalRMS > 0.,
        N[globalPeak/globalRMS],
        Null
    ];
    crestFactorDB = If[finiteRealQ[crestFactor] && crestFactor > 0., N[20. Log10[crestFactor]], Null];
    localDynamicRangeDB = If[
        Length[nonSilentRMSDBFS] >= 2,
        With[{range = Quantile[nonSilentRMSDBFS, {.1, .95}]}, N[Last[range] - First[range]]],
        Null
    ];
    windowCount = Length[timeSeriesPairs[rmsSeries]];
    pitchStatus = If[Length[pitchValues] >= 3, "AVAILABLE", "UNAVAILABLE"];
    pitchReason = If[
        pitchStatus === "AVAILABLE",
        "",
        "Fewer than three locally voiced windows yielded a reliable fundamental-frequency estimate."
    ];
    audioDuration = secondsMagnitude[AudioMeasurements[audio, "Duration"]];
    sampleRate = Round[AudioMeasurements[audio, "SampleRate"]];
    analytics = <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "method" -> "Wolfram AudioLocalMeasurements over configured overlapping windows",
        "dynamics" -> <|
            "rms_amplitude" -> distributionStatistics[rmsValues],
            "peak_amplitude" -> distributionStatistics[peakValues],
            "rms_dbfs" -> distributionStatistics[rmsDBFSValues],
            "local_loudness" -> distributionStatistics[loudnessValues],
            "crest_factor" -> crestFactor,
            "crest_factor_db" -> crestFactorDB,
            "local_dynamic_range_db" -> localDynamicRangeDB
        |>,
        "distribution" -> <|
            "rms_amplitude_histogram" -> histogramSummary[rmsValues],
            "rms_dbfs_histogram" -> histogramSummary[rmsDBFSValues]
        |>,
        "frequency" -> <|
            "spectral_centroid_hz" -> distributionStatistics[centroidValues],
            "spectral_spread_hz" -> distributionStatistics[spreadValues],
            "zero_crossing_rate" -> distributionStatistics[zeroCrossingValues],
            "nyquist_frequency_hz" -> N[sampleRate/2.]
        |>,
        "pitch" -> <|
            "status" -> pitchStatus,
            "reason" -> pitchReason,
            "method" -> "AudioLocalMeasurements/FundamentalFrequency",
            "observation_count" -> Length[pitchValues],
            "window_count" -> windowCount,
            "coverage_fraction" -> If[windowCount > 0, N[Length[pitchValues]/windowCount], 0.],
            "fundamental_frequency_hz" -> distributionStatistics[pitchValues]
        |>,
        "availability" -> <|
            "rms_amplitude" -> featureAvailability[rmsSeries, "RMS amplitude was not available."],
            "peak_amplitude" -> featureAvailability[peakSeries, "Local peak amplitude was not available."],
            "spectral_centroid" -> featureAvailability[centroidSeries, "Spectral centroid was not available."],
            "spectral_spread" -> featureAvailability[spreadSeries, "Spectral spread was not available."],
            "zero_crossing_rate" -> featureAvailability[zeroCrossingSeries, "Zero-crossing rate was not available."],
            "local_loudness" -> featureAvailability[loudnessSeries, "Local loudness was not available."],
            "fundamental_frequency" -> If[
                pitchStatus === "AVAILABLE",
                featureAvailability[pitchSeries, "Fundamental frequency was not available."],
                <|"status" -> pitchStatus, "observation_count" -> Length[pitchValues], "reason" -> pitchReason|>
            ]
        |>
    |>;
    summary = <|
        "duration_seconds" -> N[mediaDuration],
        "audio_duration_seconds" -> audioDuration,
        "sample_rate_hz" -> sampleRate,
        "channel_count" -> Round[AudioMeasurements[audio, "Channels"]],
        "rms_amplitude" -> globalRMS,
        "peak_amplitude" -> globalPeak,
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
        "peak_series" -> peakSeries,
        "spectral_spread_series" -> spreadSeries,
        "zero_crossing_rate_series" -> zeroCrossingSeries,
        "loudness_series" -> loudnessSeries,
        "pitch_series" -> pitchSeries,
        "measurement_series" -> namedSeries,
        "analytics" -> analytics,
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
        "video_analytics" -> frameAnalysis["analytics"],
        "video_summary" -> frameAnalysis["summary"],
        "audio_analysis" -> audioAnalysis,
        "capabilities" -> capabilities
    |>
];
