"""Pydantic response models for the Command Center backend's own API.

These describe the Command Center's own responses, not IRIS's. No IRIS
response field is modeled here yet — that starts once specific verified
endpoints are wired up in a later step.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
