/// Ask IRIS — the Vector Search + LLM/LangChain bonus feature's IRIS-side
/// entry point. Thin by design: all real logic lives in
/// iris/python/ask_iris.py (pure-function chunking is independently unit
/// tested in iris/python/tests/, no IRIS required). This class's job is
/// bridging ObjectScript <-> Python and distinguishing "not configured yet"
/// from a genuine error, so callers can render each state appropriately.
/// See docs/ask-iris.md for the full design writeup.
Class ISOE.AskIris Extends %RegisteredObject
{

/// Retrieval-augmented answer: retrieves grounding chunks via IRIS Vector
/// Search, then asks the chat model to answer using only that context.
/// questionJSON: {"question": "..."}
ClassMethod Ask(questionJSON As %String = "") As %String [ Language = python ]
{
    import json
    import traceback
    from ask_iris import AskIrisNotConfiguredError, ask

    try:
        payload = json.loads(questionJSON) if questionJSON else {}
    except (ValueError, TypeError):
        payload = {}
    question = (payload.get("question") or "").strip()

    if not question:
        return json.dumps({
            "status": {"errors": [{"error": "question is required", "code": "bad_request"}], "summary": "question is required"},
            "console": [],
            "result": {},
        })

    try:
        result = ask(question)
        return json.dumps({"status": {"errors": [], "summary": ""}, "console": [], "result": result})
    except AskIrisNotConfiguredError as exc:
        return json.dumps({
            "status": {"errors": [{"error": str(exc), "code": "not_configured"}], "summary": str(exc)},
            "console": [],
            "result": {},
        })
    except Exception as exc:
        return json.dumps({
            "status": {"errors": [{"error": str(exc), "code": "error"}], "summary": "Ask IRIS error: " + str(exc)},
            "console": [traceback.format_exc()],
            "result": {},
        })
}

/// Rebuilds the vector index from the docs corpus. No request body needed.
ClassMethod Reindex() As %String [ Language = python ]
{
    import json
    import traceback
    from ask_iris import AskIrisNotConfiguredError, reindex

    try:
        result = reindex()
        return json.dumps({"status": {"errors": [], "summary": ""}, "console": [], "result": result})
    except AskIrisNotConfiguredError as exc:
        return json.dumps({
            "status": {"errors": [{"error": str(exc), "code": "not_configured"}], "summary": str(exc)},
            "console": [],
            "result": {},
        })
    except Exception as exc:
        return json.dumps({
            "status": {"errors": [{"error": str(exc), "code": "error"}], "summary": "Ask IRIS reindex error: " + str(exc)},
            "console": [traceback.format_exc()],
            "result": {},
        })
}

/// Cheap, side-effect-free check: is an API key configured, and has an
/// index been built. Never raises -- always returns a result.
ClassMethod Status() As %String [ Language = python ]
{
    import json
    import traceback
    from ask_iris import status

    try:
        result = status()
        return json.dumps({"status": {"errors": [], "summary": ""}, "console": [], "result": result})
    except Exception as exc:
        return json.dumps({
            "status": {"errors": [{"error": str(exc), "code": "error"}], "summary": "Ask IRIS status error: " + str(exc)},
            "console": [traceback.format_exc()],
            "result": {},
        })
}

}
