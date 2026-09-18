"""Shared FastAPI dependencies. The single IRISClient instance is created
once at application startup (see app/main.py's lifespan) and reused across
requests, so routes never construct their own client or duplicate the
authentication/session logic it wraps."""

from fastapi import Request

from app.iris_client.client import IRISClient


def get_iris_client(request: Request) -> IRISClient:
    return request.app.state.iris_client
