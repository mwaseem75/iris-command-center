/// REST dispatch for the HealthAnalyzer bonus feature. Deployed as its own
/// web application (/api/health) rather than added to IRIS's built-in
/// %Api.Admin — that class belongs to InterSystems, not this project.
/// Authentication (Password) is enforced by the web application config, not
/// this class — see docs/health-analyzer.md for how /api/health is created.
Class ISOE.HealthAnalyzerREST Extends %CSP.REST
{

Parameter CHARSET = "UTF-8";

Parameter HandleCorsRequest = 1;

XData UrlMap
{
<Routes>
<Route Url="/analyze" Method="POST" Call="Analyze"/>
</Routes>
}

ClassMethod Analyze() As %Status
{
    set %response.ContentType = "application/json"
    set body = ""
    if %request.Content '= "" {
        set body = %request.Content.Read()
    }
    set result = ##class(ISOE.HealthAnalyzer).Analyze(body)
    write result
    quit $$$OK
}

}
