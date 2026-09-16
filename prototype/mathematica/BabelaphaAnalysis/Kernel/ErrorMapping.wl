PackageExported[FailureExitCode]
PackageExported[FailureReason]

PackageScoped[AnalysisException]
PackageScoped[InvalidInputException]
PackageScoped[IntegrityException]
PackageScoped[DependencyException]
PackageScoped[AnalysisRuntimeException]
PackageScoped[ExportException]
PackageScoped[throwAnalysisException]

If[! TrueQ[ExceptionTypeRegisteredQ[AnalysisException]],
    RegisterExceptionType[AnalysisException]
];
If[! TrueQ[ExceptionTypeRegisteredQ[InvalidInputException]],
    RegisterExceptionType[InvalidInputException, AnalysisException]
];
If[! TrueQ[ExceptionTypeRegisteredQ[IntegrityException]],
    RegisterExceptionType[IntegrityException, AnalysisException]
];
If[! TrueQ[ExceptionTypeRegisteredQ[DependencyException]],
    RegisterExceptionType[DependencyException, AnalysisException]
];
If[! TrueQ[ExceptionTypeRegisteredQ[AnalysisRuntimeException]],
    RegisterExceptionType[AnalysisRuntimeException, AnalysisException]
];
If[! TrueQ[ExceptionTypeRegisteredQ[ExportException]],
    RegisterExceptionType[ExportException, AnalysisException]
];

throwAnalysisException[tag_Symbol, reason_String, message_String, exitCode_Integer, details_: <||>] :=
    ThrowException[
        tag,
        Join[
            <|
                "Reason" -> reason,
                "Message" -> message,
                "ExitCode" -> exitCode
            |>,
            If[AssociationQ[details], details, <|"Details" -> ToString[details, InputForm]|>]
        ]
    ];

FailureExitCode[failure_Failure] := Lookup[failure[[2]], "ExitCode", 20];
FailureExitCode[_] := 20;

FailureReason[failure_Failure] := Lookup[failure[[2]], "Reason", "UNEXPECTED_FAILURE"];
FailureReason[_] := "UNEXPECTED_FAILURE";
