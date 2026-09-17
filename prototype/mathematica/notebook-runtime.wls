ClearAll[
    BabelaphaNotebookCellTags,
    BabelaphaNotebookTaggedBoxes,
    BabelaphaNotebookHeldExpression,
    BabelaphaNotebookEvaluateTag,
    BabelaphaNotebookTaggedSource
];

BabelaphaNotebookCellTags[Cell[_, _, options___]] := Flatten@{
    FirstCase[{options}, (CellTags -> value_) :> value, {}]
};

BabelaphaNotebookTaggedBoxes[path_String, tag_String] := Module[
    {notebook},
    notebook = Quiet[Check[Get[path], $Failed]];
    If[notebook === $Failed, Return[$Failed]];
    Cases[
        notebook,
        cell : Cell[BoxData[boxes_], _, ___] /;
            MemberQ[BabelaphaNotebookCellTags[cell], tag] :> boxes,
        Infinity
    ]
];

BabelaphaNotebookHeldExpression[boxes_] := ToExpression[
    boxes,
    If[StringQ[boxes], InputForm, StandardForm],
    HoldComplete
];

BabelaphaNotebookEvaluateTag[path_String, tag_String] := Module[
    {boxes, held, index, result = Null},
    boxes = BabelaphaNotebookTaggedBoxes[path, tag];
    If[boxes === $Failed || boxes === {}, Return[$Failed]];
    Do[
        held = Quiet[BabelaphaNotebookHeldExpression[boxes[[index]]]];
        If[held === $Failed, Return[$Failed]];
        result = ReleaseHold[held],
        {index, Length[boxes]}
    ];
    result
];

BabelaphaNotebookTaggedSource[path_String, tag_String] := Module[{boxes},
    boxes = BabelaphaNotebookTaggedBoxes[path, tag];
    If[boxes === $Failed || boxes === {}, Return[$Failed]];
    StringRiffle[
        (If[StringQ[#], #, ToString[BabelaphaNotebookHeldExpression[#], InputForm]]) & /@ boxes,
        "\n\n"
    ]
];
