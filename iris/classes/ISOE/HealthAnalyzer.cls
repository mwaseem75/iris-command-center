/// HealthAnalyzer — the Embedded Python bonus feature's IRIS-side entry point.
/// Thin by design: all real logic lives in iris/python/health_analyzer.py,
/// which is independently unit-tested (iris/python/tests/) without needing
/// IRIS at all. This class's only job is bridging ObjectScript <-> Python:
/// deserialize the request body, call the Python function, serialize the
/// result. See docs/health-analyzer.md for the full design writeup.
Class ISOE.HealthAnalyzer Extends %RegisteredObject
{

/// Calls health_analyzer.gather_and_analyze() with caller-supplied IRIS
/// metrics (already gathered by the frontend via the documented SysAdmin
/// REST API — see docs/api-matrix.md — not re-derived here) and returns the
/// JSON-encoded analysis. inputsJSON may be "" or "{}" for Python-only
/// (CPU/memory) analysis with no IRIS context.
ClassMethod Analyze(inputsJSON As %String = "") As %String [ Language = python ]
{
    import json
    import traceback

    try:
        iris_metrics = json.loads(inputsJSON) if inputsJSON else {}
    except (ValueError, TypeError):
        iris_metrics = {}

    try:
        from health_analyzer import gather_and_analyze
        result = gather_and_analyze(iris_metrics)
        return json.dumps({"status": {"errors": [], "summary": ""}, "console": [], "result": result})
    except Exception as exc:
        return json.dumps({
            "status": {"errors": [str(exc)], "summary": "HealthAnalyzer error: " + str(exc)},
            "console": [traceback.format_exc()],
            "result": {},
        })
}

}
