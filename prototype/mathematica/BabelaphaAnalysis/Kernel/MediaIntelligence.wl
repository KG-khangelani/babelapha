PackageScoped[deriveMediaIntelligence]

mediaNestedLookup[value_, {}, _] := value;
mediaNestedLookup[value_Association, {key_, rest___}, default_] := If[
    KeyExistsQ[value, key],
    mediaNestedLookup[value[key], {rest}, default],
    default
];
mediaNestedLookup[_, _, default_] := default;

mediaCleanIntervals[intervals_] := SortBy[
    Select[
        If[ListQ[intervals], intervals, {}],
        ListQ[#] && Length[#] == 2 && AllTrue[#, finiteRealQ] && Last[#] > First[#] &
    ],
    First
];

mediaIntervalDuration[intervals_List] := Total[(Last[#] - First[#]) & /@ intervals];

mediaMergeActivityRegions[intervals_List, maximumGap_?NumericQ, minimumDuration_?NumericQ] := Module[
    {clean, merged = {}, current, result},
    clean = mediaCleanIntervals[intervals];
    If[clean === {}, Return[{}]];
    current = <|
        "start_seconds" -> N[clean[[1, 1]]],
        "end_seconds" -> N[clean[[1, 2]]],
        "active_duration_seconds" -> N[clean[[1, 2]] - clean[[1, 1]]],
        "interval_count" -> 1
    |>;
    Do[
        If[N[interval[[1]] - current["end_seconds"]] <= maximumGap,
            current["end_seconds"] = N[Max[current["end_seconds"], interval[[2]]]];
            current["active_duration_seconds"] = N[current["active_duration_seconds"] + interval[[2]] - interval[[1]]];
            current["interval_count"] = current["interval_count"] + 1,
            AppendTo[merged, current];
            current = <|
                "start_seconds" -> N[interval[[1]]],
                "end_seconds" -> N[interval[[2]]],
                "active_duration_seconds" -> N[interval[[2]] - interval[[1]]],
                "interval_count" -> 1
            |>
        ],
        {interval, Rest[clean]}
    ];
    AppendTo[merged, current];
    result = Select[merged, #["end_seconds"] - #["start_seconds"] >= minimumDuration &];
    MapIndexed[
        Function[{region, index},
            With[{duration = N[region["end_seconds"] - region["start_seconds"]]},
                Join[
                    <|"region_index" -> First[index]|>,
                    region,
                    <|
                        "duration_seconds" -> duration,
                        "activity_fraction" -> If[duration > 0., N[region["active_duration_seconds"]/duration], 0.]
                    |>
                ]
            ]
        ],
        result
    ]
];

mediaAudioActivity[media_Association, parameters_Association] := Module[
    {available, summary, duration, intervals, mergeGap = .20, minimumDuration = .20, coverage, regions},
    available = TrueQ[mediaNestedLookup[media, {"audio_analysis", "available"}, False]];
    summary = mediaNestedLookup[media, {"audio_analysis", "summary"}, <||>];
    duration = mediaNestedLookup[summary, {"audio_duration_seconds"}, mediaNestedLookup[media, {"duration_seconds"}, Null]];
    intervals = mediaCleanIntervals[mediaNestedLookup[summary, {"audible_intervals_seconds"}, {}]];
    If[! available || ! finiteRealQ[duration] || duration <= 0.,
        Return[<|
            "status" -> "UNAVAILABLE",
            "reason" -> "No decodable audio track was available for activity segmentation.",
            "method" -> "RMS-threshold intervals merged across short gaps; activity is not speaker diarization",
            "threshold_dbfs" -> N[Lookup[parameters, "silence_threshold_db", -40.]],
            "merge_gap_seconds" -> mergeGap,
            "minimum_region_seconds" -> minimumDuration,
            "audible_coverage_fraction" -> Null,
            "regions" -> {}
        |>]
    ];
    coverage = Clip[N[mediaIntervalDuration[intervals]/duration], {0., 1.}];
    regions = mediaMergeActivityRegions[intervals, mergeGap, minimumDuration];
    <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "method" -> "RMS-threshold intervals merged across short gaps; activity is not speaker diarization",
        "threshold_dbfs" -> N[Lookup[parameters, "silence_threshold_db", -40.]],
        "merge_gap_seconds" -> mergeGap,
        "minimum_region_seconds" -> minimumDuration,
        "audible_coverage_fraction" -> coverage,
        "regions" -> regions
    |>
];

mediaSentenceParts[text_String] := Select[
    StringTrim /@ StringCases[text, RegularExpression["[^.!?]+[.!?]*"]],
    # =!= "" &
];

mediaSplitTranscriptSegment[segment_Association, sourceIndex_Integer] := Module[
    {start, finish, text, sentences, counts, weights, starts, ends, basis},
    start = N[Lookup[segment, "start_seconds", 0.]];
    finish = N[Lookup[segment, "end_seconds", start]];
    text = ToString[Lookup[segment, "text", ""]];
    sentences = mediaSentenceParts[text];
    If[sentences === {}, Return[{}]];
    counts = Max[1, Length[TextWords[#]]] & /@ sentences;
    weights = N[counts/Total[counts]];
    starts = start + (finish - start) Prepend[Accumulate[Most[weights]], 0.];
    ends = start + (finish - start) Accumulate[weights];
    If[ends =!= {}, ends[[-1]] = finish];
    basis = If[Length[sentences] > 1, "PROPORTIONAL_WITHIN_SOURCE_SEGMENT", "SOURCE_SEGMENT"];
    MapThread[
        Function[{sentence, wordCount, segmentStart, segmentEnd, localIndex},
            <|
                "source_segment_index" -> sourceIndex,
                "sentence_index" -> localIndex,
                "start_seconds" -> N[segmentStart],
                "end_seconds" -> N[segmentEnd],
                "duration_seconds" -> N[Max[0., segmentEnd - segmentStart]],
                "text" -> sentence,
                "word_count" -> wordCount,
                "timing_basis" -> basis
            |>
        ],
        {sentences, counts, starts, ends, Range[Length[sentences]]}
    ]
];

mediaSpeechSegments[media_Association] := Module[
    {transcript, status, sourceSegments, duration, text, segments, basis},
    transcript = mediaNestedLookup[media, {"transcript"}, <||>];
    status = ToUpperCase@ToString[Lookup[transcript, "status", "UNAVAILABLE"]];
    If[status =!= "AVAILABLE",
        Return[<|
            "status" -> "UNAVAILABLE",
            "reason" -> ToString[Lookup[transcript, "reason", "No transcript was available for speech navigation."]],
            "method" -> "sentence navigation derived from verified transcript segments",
            "timing_basis" -> "UNAVAILABLE",
            "speaker_diarization" -> "NOT_PERFORMED",
            "segment_count" -> 0,
            "segments" -> {}
        |>]
    ];
    duration = N[mediaNestedLookup[media, {"duration_seconds"}, 0.]];
    text = ToString[Lookup[transcript, "text", ""]];
    sourceSegments = Select[Lookup[transcript, "segments", {}], AssociationQ];
    If[sourceSegments === {} && StringTrim[text] =!= "",
        sourceSegments = {<|"start_seconds" -> 0., "end_seconds" -> duration, "text" -> text|>}
    ];
    segments = Flatten@MapIndexed[mediaSplitTranscriptSegment[#1, First[#2]] &, sourceSegments];
    segments = MapIndexed[Join[<|"segment_index" -> First[#2]|>, #1] &, segments];
    basis = If[
        AnyTrue[segments, Lookup[#, "timing_basis", ""] === "PROPORTIONAL_WITHIN_SOURCE_SEGMENT" &],
        "MIXED_WITH_ESTIMATED_SENTENCE_TIMING",
        "SOURCE_SEGMENTS"
    ];
    <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "method" -> "sentence navigation derived from verified transcript segments; proportional boundaries are estimates, not word timestamps",
        "timing_basis" -> basis,
        "speaker_diarization" -> "NOT_PERFORMED",
        "segment_count" -> Length[segments],
        "segments" -> segments
    |>
];

mediaConsolidatedSceneCandidates[candidates_, minimumSeparation_?NumericQ] := Module[
    {ordered, selected = {}, previousTime, currentTime},
    ordered = SortBy[
        Select[
            If[ListQ[candidates], candidates, {}],
            AssociationQ[#] && finiteRealQ[Lookup[#, "time_seconds", Null]] && finiteRealQ[Lookup[#, "score", Null]] &
        ],
        Lookup[#, "time_seconds"] &
    ];
    Do[
        currentTime = N[Lookup[candidate, "time_seconds"]];
        If[selected === {},
            AppendTo[selected, candidate],
            previousTime = N[Lookup[Last[selected], "time_seconds"]];
            If[currentTime - previousTime >= minimumSeparation,
                AppendTo[selected, candidate],
                If[Lookup[candidate, "score"] > Lookup[Last[selected], "score"], selected[[-1]] = candidate]
            ]
        ],
        {candidate, ordered}
    ];
    selected
];

mediaNearestRecord[records_List, time_?NumericQ] := If[
    records === {},
    Missing["NotAvailable"],
    First@MinimalBy[records, Abs[N[Lookup[#, "time_seconds", 0.]] - time] &]
];

mediaSceneSegments[media_Association] := Module[
    {duration, analytics, rows, rawCandidates, candidates, minimumSeparation = .50,
     boundaries, intervals, segmentCount, segments},
    duration = N[mediaNestedLookup[media, {"duration_seconds"}, 0.]];
    analytics = mediaNestedLookup[media, {"video_analytics"}, <||>];
    rows = Select[Lookup[analytics, "per_frame", {}], AssociationQ];
    rawCandidates = mediaNestedLookup[analytics, {"scene_changes", "candidates"}, {}];
    candidates = mediaConsolidatedSceneCandidates[rawCandidates, minimumSeparation];
    If[rows === {} || duration <= 0.,
        Return[<|
            "status" -> "UNAVAILABLE",
            "reason" -> "No timestamped video samples were available for scene segmentation.",
            "method" -> "contiguous scenes bounded by consolidated visual-change candidates",
            "minimum_separation_seconds" -> minimumSeparation,
            "boundary_count" -> 0,
            "segments" -> {}
        |>]
    ];
    boundaries = Sort@DeleteDuplicates@Join[
        {0.},
        Select[N[Lookup[candidates, "time_seconds", {}]], 0. < # < duration &],
        {duration}
    ];
    intervals = Partition[boundaries, 2, 1];
    segmentCount = Length[intervals];
    segments = MapIndexed[
        Function[{interval, indexSpec},
            Module[{index = First[indexSpec], start, finish, members, midpoint, representative, entryCandidate},
                {start, finish} = N[interval];
                members = Select[
                    rows,
                    With[{time = N[Lookup[#, "time_seconds", 0.]]},
                        time >= start && If[index == segmentCount, time <= finish, time < finish]
                    ] &
                ];
                midpoint = N[(start + finish)/2.];
                If[members === {}, members = {mediaNearestRecord[rows, midpoint]}];
                representative = mediaNearestRecord[members, midpoint];
                entryCandidate = If[
                    index == 1,
                    Missing["NotApplicable"],
                    mediaNearestRecord[candidates, start]
                ];
                <|
                    "scene_index" -> index,
                    "start_seconds" -> start,
                    "end_seconds" -> finish,
                    "duration_seconds" -> N[finish - start],
                    "sample_count" -> Length[members],
                    "representative_time_seconds" -> N[Lookup[representative, "time_seconds", midpoint]],
                    "mean_brightness" -> N[Mean[Lookup[members, "brightness", 0.]]],
                    "mean_motion" -> N[Mean[Lookup[members, "frame_difference", 0.]]],
                    "mean_colorfulness" -> N[Mean[Lookup[members, "colorfulness", 0.]]],
                    "representative_color_hex" -> ToString[Lookup[representative, "mean_color_hex", "#000000"]],
                    "entry_boundary_score" -> If[MissingQ[entryCandidate], Null, N[Lookup[entryCandidate, "score", 0.]]]
                |>
            ]
        ],
        intervals
    ];
    <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "method" -> "contiguous scenes bounded by consolidated visual-change candidates; boundaries are screening results, not semantic edits",
        "minimum_separation_seconds" -> minimumSeparation,
        "boundary_count" -> Length[candidates],
        "segments" -> segments
    |>
];

mediaSeriesPairs[series_TimeSeries] := Module[{pairs = Normal[series]},
    If[ListQ[pairs] && AllTrue[pairs, ListQ[#] && Length[#] == 2 && AllTrue[#, finiteRealQ] &], N[pairs], {}]
];
mediaSeriesPairs[_] := {};

mediaNormalizeUnit[values_List] := Module[{range},
    If[values === {}, Return[{}]];
    range = MinMax[N[values]];
    If[Last[range] - First[range] <= 10.^-12,
        ConstantArray[0., Length[values]],
        N[(values - First[range])/(Last[range] - First[range])]
    ]
];

mediaTimeInIntervalsQ[time_?NumericQ, intervals_List] := AnyTrue[
    intervals,
    First[#] <= time <= Last[#] &
];

mediaTranscriptAtTime[transcript_Association, time_?NumericQ] := Module[{segment},
    segment = SelectFirst[
        Select[Lookup[transcript, "segments", {}], AssociationQ],
        Lookup[#, "start_seconds", Infinity] <= time <= Lookup[#, "end_seconds", -Infinity] &,
        Missing["NotAvailable"]
    ];
    If[MissingQ[segment], Null, ToString[Lookup[segment, "text", ""]]]
];

mediaCrossModal[media_Association] := Module[
    {duration, analytics, rows, rmsPairs, intervals, transcript, candidates, alignedBase,
     motionValues, rmsValues, motionNormalized, rmsNormalized, aligned, correlation,
     sceneEvents, peakEvent, events, nearest, time, score, peak},
    duration = N[mediaNestedLookup[media, {"duration_seconds"}, 0.]];
    analytics = mediaNestedLookup[media, {"video_analytics"}, <||>];
    rows = Select[Lookup[analytics, "per_frame", {}], AssociationQ];
    rmsPairs = mediaSeriesPairs[mediaNestedLookup[media, {"audio_analysis", "rms_series"}, None]];
    intervals = mediaCleanIntervals[mediaNestedLookup[media, {"audio_analysis", "summary", "audible_intervals_seconds"}, {}]];
    transcript = mediaNestedLookup[media, {"transcript"}, <||>];
    candidates = mediaConsolidatedSceneCandidates[
        mediaNestedLookup[analytics, {"scene_changes", "candidates"}, {}],
        .50
    ];
    If[rows === {} || rmsPairs === {},
        Return[<|
            "status" -> "UNAVAILABLE",
            "reason" -> "Cross-modal alignment requires timestamped video samples and a decodable audio RMS series.",
            "method" -> "nearest-time alignment of video motion and audio RMS; Pearson correlation is descriptive, not causal",
            "sample_count" -> 0,
            "motion_rms_pearson_correlation" -> Null,
            "aligned_samples" -> {},
            "events" -> {}
        |>]
    ];
    alignedBase = Map[
        Function[row,
            time = N[Lookup[row, "time_seconds", 0.]];
            nearest = First@MinimalBy[rmsPairs, Abs[First[#] - time] &];
            <|
                "time_seconds" -> time,
                "motion" -> N[Lookup[row, "frame_difference", 0.]],
                "rms_amplitude" -> N[Last[nearest]]
            |>
        ],
        rows
    ];
    motionValues = N[Lookup[alignedBase, "motion"]];
    rmsValues = N[Lookup[alignedBase, "rms_amplitude"]];
    motionNormalized = mediaNormalizeUnit[motionValues];
    rmsNormalized = mediaNormalizeUnit[rmsValues];
    aligned = MapThread[
        Join[#1, <|"motion_normalized" -> #2, "rms_normalized" -> #3|>] &,
        {alignedBase, motionNormalized, rmsNormalized}
    ];
    correlation = If[
        Length[aligned] >= 3 && StandardDeviation[motionValues] > 10.^-12 && StandardDeviation[rmsValues] > 10.^-12,
        N[Correlation[motionValues, rmsValues]],
        Null
    ];
    sceneEvents = Map[
        Function[candidate,
            time = N[Lookup[candidate, "time_seconds", 0.]];
            nearest = mediaNearestRecord[aligned, time];
            score = Clip[N[(Lookup[candidate, "score", 0.] + Lookup[nearest, "rms_normalized", 0.])/2.], {0., 1.}];
            <|
                "event_type" -> If[mediaTimeInIntervalsQ[time, intervals], "SCENE_CHANGE_WITH_AUDIO", "SCENE_CHANGE_IN_SILENCE"],
                "time_seconds" -> time,
                "window_seconds" -> {Max[0., time - .25], Min[duration, time + .25]},
                "score" -> score,
                "scene_score" -> N[Lookup[candidate, "score", 0.]],
                "motion" -> N[Lookup[nearest, "motion", 0.]],
                "rms_amplitude" -> N[Lookup[nearest, "rms_amplitude", 0.]],
                "motion_normalized" -> N[Lookup[nearest, "motion_normalized", 0.]],
                "rms_normalized" -> N[Lookup[nearest, "rms_normalized", 0.]],
                "audio_activity" -> mediaTimeInIntervalsQ[time, intervals],
                "transcript_text" -> mediaTranscriptAtTime[transcript, time],
                "evidence_paths" -> {
                    "measurements.video_analytics.scene_changes.candidates",
                    "measurements.cross_modal.aligned_samples"
                }
            |>
        ],
        candidates
    ];
    peak = First@MaximalBy[aligned, Mean[Lookup[#, {"motion_normalized", "rms_normalized"}, {0., 0.}]] &];
    time = N[Lookup[peak, "time_seconds", 0.]];
    score = Clip[N[Mean[Lookup[peak, {"motion_normalized", "rms_normalized"}, {0., 0.}]]], {0., 1.}];
    peakEvent = <|
        "event_type" -> "AUDIO_VISUAL_PEAK",
        "time_seconds" -> time,
        "window_seconds" -> {Max[0., time - .25], Min[duration, time + .25]},
        "score" -> score,
        "scene_score" -> Null,
        "motion" -> N[Lookup[peak, "motion", 0.]],
        "rms_amplitude" -> N[Lookup[peak, "rms_amplitude", 0.]],
        "motion_normalized" -> N[Lookup[peak, "motion_normalized", 0.]],
        "rms_normalized" -> N[Lookup[peak, "rms_normalized", 0.]],
        "audio_activity" -> mediaTimeInIntervalsQ[time, intervals],
        "transcript_text" -> mediaTranscriptAtTime[transcript, time],
        "evidence_paths" -> {
            "measurements.cross_modal.aligned_samples"
        }
    |>;
    events = SortBy[Append[sceneEvents, peakEvent], {Lookup[#, "time_seconds"] &, Lookup[#, "event_type"] &}];
    events = MapIndexed[Join[<|"event_index" -> First[#2]|>, #1] &, events];
    <|
        "status" -> "AVAILABLE",
        "reason" -> "",
        "method" -> "nearest-time alignment of video motion and audio RMS; min-max normalization and Pearson correlation are descriptive, not causal",
        "sample_count" -> Length[aligned],
        "motion_rms_pearson_correlation" -> correlation,
        "aligned_samples" -> aligned,
        "events" -> events
    |>
];

mediaPercentString[value_?NumericQ] := ToString[N[Round[1000. value]/10.]] <> "%";
mediaNumberString[value_?NumericQ, scale_: 1000.] := ToString[N[Round[scale value]/scale]];

mediaInsights[audioActivity_Association, speechSegments_Association, sceneSegments_Association, crossModal_Association, transcript_Association] := Module[
    {items = {}, coverage, scenes, words, correlation, peak, indexed},
    If[Lookup[audioActivity, "status", ""] === "AVAILABLE",
        coverage = Lookup[audioActivity, "audible_coverage_fraction", 0.];
        AppendTo[items, <|
            "kind" -> "OBSERVATION",
            "headline" -> "Measured audio activity",
            "statement" -> "Above-threshold audio occupies " <> mediaPercentString[coverage] <> " of the source; this is an RMS activity measure, not speaker diarization.",
            "time_seconds" -> Null,
            "evidence_paths" -> {"measurements.audio_activity.audible_coverage_fraction", "measurements.audible_intervals_seconds"}
        |>]
    ];
    If[Lookup[sceneSegments, "status", ""] === "AVAILABLE",
        scenes = Length[Lookup[sceneSegments, "segments", {}]];
        AppendTo[items, <|
            "kind" -> "OBSERVATION",
            "headline" -> "Visual structure",
            "statement" -> ToString[scenes] <> " contiguous visual scene segment(s) were formed from " <> ToString[Lookup[sceneSegments, "boundary_count", 0]] <> " consolidated change boundary candidate(s).",
            "time_seconds" -> Null,
            "evidence_paths" -> {"measurements.scene_segments.segments", "measurements.video_analytics.scene_changes.candidates"}
        |>]
    ];
    If[Lookup[speechSegments, "status", ""] === "AVAILABLE",
        words = mediaNestedLookup[transcript, {"statistics", "word_count"}, 0];
        AppendTo[items, <|
            "kind" -> "OBSERVATION",
            "headline" -> "Speech text available",
            "statement" -> "The verified transcript contains " <> ToString[words] <> " word(s) and " <> ToString[Lookup[speechSegments, "segment_count", 0]] <> " sentence-level navigation segment(s).",
            "time_seconds" -> Null,
            "evidence_paths" -> {"measurements.transcript.statistics", "measurements.speech_segments.segments"}
        |>];
        If[Lookup[speechSegments, "timing_basis", ""] === "MIXED_WITH_ESTIMATED_SENTENCE_TIMING",
            AppendTo[items, <|
                "kind" -> "LIMITATION",
                "headline" -> "Sentence timing is estimated",
                "statement" -> "Sentence boundaries were allocated proportionally inside verified source transcript segments; they are navigation aids, not model-emitted word timestamps.",
                "time_seconds" -> Null,
                "evidence_paths" -> {"measurements.speech_segments.method", "measurements.speech_segments.timing_basis"}
            |>]
        ]
    ];
    correlation = Lookup[crossModal, "motion_rms_pearson_correlation", Null];
    If[finiteRealQ[correlation],
        AppendTo[items, <|
            "kind" -> "OBSERVATION",
            "headline" -> "Audio-motion alignment",
            "statement" -> "Aligned RMS amplitude and visual motion have a descriptive Pearson correlation of " <> mediaNumberString[correlation] <> " across " <> ToString[Lookup[crossModal, "sample_count", 0]] <> " sampled times; this does not establish causation.",
            "time_seconds" -> Null,
            "evidence_paths" -> {"measurements.cross_modal.motion_rms_pearson_correlation", "measurements.cross_modal.aligned_samples"}
        |>]
    ];
    peak = SelectFirst[Lookup[crossModal, "events", {}], Lookup[#, "event_type", ""] === "AUDIO_VISUAL_PEAK" &, Missing["NotAvailable"]];
    If[! MissingQ[peak],
        AppendTo[items, <|
            "kind" -> "OBSERVATION",
            "headline" -> "Strongest joint activity",
            "statement" -> "The strongest jointly normalized audio-motion sample occurs at " <> mediaNumberString[Lookup[peak, "time_seconds", 0.], 100.] <> " seconds with score " <> mediaNumberString[Lookup[peak, "score", 0.]] <> ".",
            "time_seconds" -> N[Lookup[peak, "time_seconds", 0.]],
            "evidence_paths" -> {"measurements.cross_modal.events", "measurements.cross_modal.aligned_samples"}
        |>]
    ];
    indexed = MapIndexed[
        Join[<|"insight_id" -> "insight-" <> IntegerString[First[#2], 10, 2]|>, #1] &,
        items
    ];
    <|
        "method" -> "deterministic descriptive rules over emitted measurements; no causal, emotional, or demographic inference",
        "items" -> indexed
    |>
];

deriveMediaIntelligence[media_Association, parameters_Association] := Module[
    {audioActivity, speechSegments, sceneSegments, crossModal, transcript, insights},
    audioActivity = mediaAudioActivity[media, parameters];
    speechSegments = mediaSpeechSegments[media];
    sceneSegments = mediaSceneSegments[media];
    crossModal = mediaCrossModal[media];
    transcript = mediaNestedLookup[media, {"transcript"}, <||>];
    insights = mediaInsights[audioActivity, speechSegments, sceneSegments, crossModal, transcript];
    <|
        "audio_activity" -> audioActivity,
        "speech_segments" -> speechSegments,
        "scene_segments" -> sceneSegments,
        "cross_modal" -> crossModal,
        "insights" -> insights
    |>
];
