Class ISOE.AskIrisREST Extends %CSP.REST
{

Parameter CHARSET = "UTF-8";

Parameter HandleCorsRequest = 1;

XData UrlMap
{
<Routes>
<Route Url="/ask" Method="POST" Call="Ask"/>
<Route Url="/reindex" Method="POST" Call="Reindex"/>
<Route Url="/status" Method="GET" Call="Status"/>
</Routes>
}

ClassMethod Ask() As %Status
{
    set %response.ContentType = "application/json"
    set body = ""
    if %request.Content '= "" {
        set body = %request.Content.Read()
    }
    set result = ##class(ISOE.AskIris).Ask(body)
    write result
    quit $$$OK
}

ClassMethod Reindex() As %Status
{
    set %response.ContentType = "application/json"
    set result = ##class(ISOE.AskIris).Reindex()
    write result
    quit $$$OK
}

ClassMethod Status() As %Status
{
    set %response.ContentType = "application/json"
    set result = ##class(ISOE.AskIris).Status()
    write result
    quit $$$OK
}

}
