"""
API Schemas — Pydantic models for request/response serialization.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, EmailStr, computed_field, ConfigDict


# ── User Schemas ─────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str = Field(..., max_length=320)
    name: str = Field(..., max_length=255)
    learning_profile: dict[str, Any] = Field(default_factory=dict)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    learning_profile: dict[str, Any]
    emotional_profile: dict[str, Any]
    mastery_scores: dict[str, Any]
    created_at: datetime


# ── Auth Schemas ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=320)
    name: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    learning_profile: dict[str, Any] = Field(default_factory=dict)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── Session Schemas ──────────────────────────────────────────────

class SessionCreate(BaseModel):
    # user_id is derived from the authenticated token; accepted for backward
    # compatibility but ignored by the server.
    user_id: Optional[uuid.UUID] = None
    topic: str = Field(..., max_length=3000)
    language: Optional[str] = Field(default="en-US", max_length=50)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    topic: str
    status: str
    summary_json: Optional[dict[str, Any]] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    @computed_field
    @property
    def duration_ms(self) -> int:
        if not self.ended_at:
            return 0
        return max(0, int((self.ended_at - self.started_at).total_seconds() * 1000))


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


# ── Timeline Event Schemas ───────────────────────────────────────

class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    generation_id: str
    branch_id: str
    version_id: str
    parent_event_id: Optional[uuid.UUID] = None
    interruption_trigger: bool
    sequence_number: int
    start_ms: int
    server_timestamp: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class SessionEventsResponse(BaseModel):
    session_id: uuid.UUID
    events: list[TimelineEventResponse]
    total: int
    branches: list[str]


# ── Health ───────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str
    environment: str
    active_ws_connections: int
    active_sessions: int


class InterruptionRequest(BaseModel):
    """Request payload for pedagogical interruption."""
    text: str = Field(..., description="Student's text input or transcription")
    gesture_data: Optional[dict[str, Any]] = Field(default=None, description="Spatial gesture metadata")
    snapshot: Optional[dict[str, Any]] = Field(default=None, description="Current client-side scene snapshot")


class ImageExtractionResponse(BaseModel):
    """Response returned after running the 3-stage vision pipeline."""
    question_text: str
    confidence: float
    contains_math: bool
    contains_diagram: bool
    diagram_description: str
    entities: list[str]
    relations: list[str]
    needs_user_review: bool
    verification_errors: list[str]
    has_multiple_questions: bool
    learning_goal: str
    math_entities: list[str]
    diagram_entities: list[str]

