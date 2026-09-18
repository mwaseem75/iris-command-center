"""Pydantic models for IRIS SysAdmin REST API responses.

These model the response shapes as actually VERIFIED against a real running
IRIS 2026.2 instance (see docs/api-capability-matrix.md), not as guessed from
mainspec_v2.json alone. Where the spec and the observed response disagree,
the model follows the observed response, and the discrepancy is noted below.

Known, deliberate divergence from mainspec_v2.json's schemas:
  - The spec's `LoginResponse`/`Info` schemas describe some fields as flat
    (no wrapper) or unwrapped; the actually observed response for every
    endpoint wired up so far (/info, /v2/namespaces, /v2/databases,
    /v2/processes) wraps its payload in {"status": ..., "console": ...,
    "result": ...}. That wrapper is modeled here as `IRISEnvelope`.
  - The spec's `BaseResponse` schema (used elsewhere in the spec) declares
    `status.Errors` (capitalized) as an array of strings. Every response
    observed for these four endpoints had an EMPTY errors array, so the
    element type was never actually confirmed for them — `errors` is
    modeled permissively (`list[Any]`) rather than assuming either shape.
    The lowercase key `errors` (not `Errors`) is what was actually observed.
  - `console` was always an empty array in every observed response for
    these endpoints; also modeled permissively for the same reason.
  - `Info.privileges` is modeled as a dict of privilege name -> {"use": bool}
    rather than fixed named fields, because the exact set of keys present
    depends on which privileges the authenticated account holds (only
    observed for `_SYSTEM`, which holds nearly all of them) — see
    docs/api-capability-matrix.md's note that `ConfigStore` was absent
    from the response even though the spec's schema lists it.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

ResultT = TypeVar("ResultT")


class IRISStatus(BaseModel):
    errors: list[Any] = Field(default_factory=list)
    summary: str = ""


class IRISEnvelope(BaseModel, Generic[ResultT]):
    status: IRISStatus
    console: list[Any] = Field(default_factory=list)
    result: ResultT


# --- GET /info ---


class AdminPrivilegeFlag(BaseModel):
    use: bool


class InfoNamespaceRef(BaseModel):
    name: str


class InfoResult(BaseModel):
    apiVersion: int
    username: str
    serverVersion: str
    systemMode: str
    product: str
    namespaces: list[InfoNamespaceRef]
    privileges: dict[str, AdminPrivilegeFlag]


# --- GET /v2/namespaces ---


class NamespaceEntry(BaseModel):
    Name: str
    Globals: str
    Routines: str
    SysGlobals: str
    SysRoutines: str
    Library: str
    TempGlobals: str


# --- GET /v2/databases ---


class DatabaseEntry(BaseModel):
    Name: str
    Directory: str
    Server: str
    ClusterMountMode: bool
    MountRequired: bool
    MountAtStartup: bool
    StreamLocation: str
    Status: str


# --- GET /v2/processes ---


class ProcessEntry(BaseModel):
    Job: int
    Pid: int
    Username: str
    Device: str
    Nspace: str
    Routine: str
    Commands: int
    Globals: int
    State: str
    ClientName: str
    EXEname: str
    IPAddress: str
    CanBeExamined: bool
    CanBeSuspended: bool
    CanBeTerminated: bool
    CanReceiveBroadcast: bool
    PrvGblBlkCnt: int
    OSUserName: str
    CPUTime: int
    ParentPid: int
    ElapsedTime: str
