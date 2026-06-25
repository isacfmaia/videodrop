"""Pydantic schemas for request and response boundaries."""

from __future__ import annotations

from pydantic import BaseModel


class ProbeRequest(BaseModel):
    """Request body used to analyze a public video URL."""

    url: str

