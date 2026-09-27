"""Pydantic schemas exposing Opportunity Validator results (Autopilot
Phase 1) over the API."""

from __future__ import annotations

from pydantic import BaseModel


class ValidationCheckRead(BaseModel):
    name: str
    passed: bool | None
    detail: str


class ValidationResultRead(BaseModel):
    checks: list[ValidationCheckRead]
    overall_passed: bool
