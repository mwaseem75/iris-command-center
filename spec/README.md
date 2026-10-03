# spec/

`mainspec_v2.json` is the InterSystems IRIS SysAdmin REST API specification
("SysAdmin APIs", version 2) the Command Center is built against: an OpenAPI
3.0 document for the API served under `/api/admin`, with 190 paths and 273
operations.

It is reference material only; nothing loads it at runtime. Where a live IRIS
response differs from the spec, the backend models follow the real response
(see `backend/app/models/iris.py`). The API Capability Explorer
(`backend/app/capabilities.py`) lists which of these endpoints the Command
Center has verified and uses.
