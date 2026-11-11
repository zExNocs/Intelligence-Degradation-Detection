"""Define persisted evaluation records and validated configuration contracts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


def identifier() -> str:
    """Return a collision-resistant identifier for a persisted record."""
    return uuid4().hex


def timestamp() -> float:
    """Return the current server timestamp in UTC seconds."""
    return datetime.now(UTC).timestamp()


class Record(BaseModel):
    """Reject unknown fields and validate assignments to internal records."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Kind(StrEnum):
    """Identify the four supported evaluation experiences."""

    PELICAN = "pelican"
    COMPARISON = "comparison"
    MODELTRACE = "modeltrace"
    OTHER = "other"


class Status(StrEnum):
    """Represent execution state independently of answer quality."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


ACTIVE = {Status.QUEUED, Status.RUNNING}


class Proxy(Record):
    """Preserve the exact proxy route assigned by an account source."""

    protocol: Literal["http", "https", "socks5", "socks5h"]
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    username: str = ""
    password: str = ""


class Credentials(Record):
    """Keep upstream secrets inside server-side records only."""

    api_key: str = ""
    access_token: str = ""
    chatgpt_account_id: str = ""
    proxy: Proxy | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class AccountInput(Record):
    """Validate editable account properties without exposing stored credentials."""

    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["openai_responses", "anthropic_messages", "openai_chat"] = (
        "openai_responses"
    )
    base_url: str = "https://api.openai.com"
    path: str = "/v1/responses"
    models_path: str = "/v1/models"
    api_key: str | None = None
    headers: dict[str, str] | None = None
    default_model: str = ""
    default_effort: str = "default"
    max_parallel: int = Field(default=1, ge=1, le=64)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Accept explicit HTTP endpoints without embedded authentication."""
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) base URL without credentials or query.")
        return value.rstrip("/")

    @field_validator("path", "models_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Keep endpoint paths relative to the configured server."""
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("Endpoint paths must start with one slash.")
        if "#" in value or "\\" in value or "://" in value:
            raise ValueError("Invalid endpoint path.")
        return value


class Account(Record):
    """Persist account routing, source identity, and user-owned preferences."""

    id: str = Field(default_factory=identifier)
    config: AccountInput
    credentials: Credentials = Field(default_factory=Credentials)
    source: Literal["direct", "sub2api"] = "direct"
    external_id: int | None = None
    source_proxy_id: int | None = None
    source_proxy_name: str | None = None
    account_type: str = "apikey"
    source_active: bool = True
    source_error: str | None = None
    synced_at: float | None = None
    last_model: str | None = None
    last_effort: str | None = None
    models: list[str] = Field(default_factory=list)
    models_at: float | None = None
    models_error: str | None = None


class TargetInput(Record):
    """Select a saved account and its invocation preferences for one check."""

    account_id: str
    model: str = Field(min_length=1, max_length=250)
    effort: str = Field(default="default", max_length=40)


class Target(TargetInput):
    """Persist one account check within a named evaluation group."""

    id: str = Field(default_factory=identifier)
    group_id: str


class GroupInput(Record):
    """Describe a versioned evaluation recipe shared by selected accounts."""

    name: str = Field(min_length=1, max_length=120)
    kind: Kind
    prompt: str = Field(default="", max_length=100_000)
    cron: str = "*/30 * * * *"
    enabled: bool = True
    comparison_mode: Literal["json", "regex"] = "json"
    expected_json: str = "{}"
    regex_pattern: str = ""
    challenge_ids: list[str] = Field(
        default_factory=lambda: ["intuition-294", "sequential-311", "immediate-329"]
    )
    parallel: bool = False
    expected_identity: str | None = None
    targets: list[TargetInput] = Field(min_length=1, max_length=100)


class Group(Record):
    """Persist a named recipe and the next due server timestamp."""

    id: str = Field(default_factory=identifier)
    recipe: GroupInput
    revision: int = 1
    next_run_at: float | None = None
    created_at: float = Field(default_factory=timestamp)


class Usage(Record):
    """Represent only token counts actually supplied by the upstream."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None


class Output(Record):
    """Normalize protocol-specific output without losing terminal state."""

    text: str = ""
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str | None = None
    elapsed: float = 0
    first_token_seconds: float | None = None


class Difference(Record):
    """Explain a structural mismatch using an unambiguous JSON path."""

    path: str
    reason: str
    expected: JsonValue = None
    actual: JsonValue = None


class Judgment(Record):
    """Separate measurable quality, reference attribution, and human review."""

    verdict: str = "unreviewed"
    score: float | None = None
    matched: int = 0
    total: int = 0
    differences: list[Difference] = Field(default_factory=list)
    analysis: dict[str, JsonValue] = Field(default_factory=dict)


class Snapshot(Record):
    """Freeze the non-secret conditions used to interpret a historical run."""

    account_name: str
    model: str
    effort: str
    protocol: str
    group_revision: int
    recipe: GroupInput
    timezone: str
    evaluator_version: str = "1"
    call_timeout: int = 600
    max_output_tokens: int = 16384
    fingerprint_version: str | None = None


class Run(Record):
    """Track one check result, independently of its individual API calls."""

    id: str = Field(default_factory=identifier)
    batch_id: str = Field(default_factory=identifier)
    group_id: str | None = None
    target_id: str | None = None
    account_id: str
    kind: str
    snapshot: Snapshot
    status: Status = Status.QUEUED
    created_at: float = Field(default_factory=timestamp)
    started_at: float | None = None
    finished_at: float | None = None
    output: Output = Field(default_factory=Output)
    judgment: Judgment = Field(default_factory=Judgment)
    error: str | None = None
    review: Literal["pass", "fail"] | None = None
    review_note: str = ""


class Call(Record):
    """Persist one independently scheduled upstream invocation."""

    id: str = Field(default_factory=identifier)
    run_id: str
    account_id: str
    order: int = 0
    challenge_id: str | None = None
    expected_count: int = 0
    prompt: str
    status: Status = Status.QUEUED
    output: Output = Field(default_factory=Output)
    error: str | None = None
    created_at: float = Field(default_factory=timestamp)


class Settings(Record):
    """Validate global defaults without changing existing evaluation recipes."""

    timezone: str = Field(default_factory=lambda: os.environ.get("TZ", "UTC"))
    default_cron: str = "*/30 * * * *"
    retention_days: int = Field(default=30, ge=1, le=3650)
    retention_count: int = Field(default=100, ge=1, le=10000)
    account_check_limit: int = Field(default=5, ge=1, le=100)
    global_parallel: int = Field(default=4, ge=1, le=128)
    call_timeout: int = Field(default=600, ge=10, le=3600)
    max_output_tokens: int = Field(default=16384, ge=256, le=262144)
    sub2api_url: str = ""
    sub2api_key: str = ""
    sync_seconds: int = Field(default=60, ge=10, le=86400)
    prompts: dict[Kind, str] = Field(
        default_factory=lambda: {
            Kind.PELICAN: "Create a delightful, polished HTML illustration of a pelican riding a bicycle. Return only one complete self-contained HTML document with inline CSS and optional inline JavaScript. Use SVG or canvas for the illustration. Do not load external images, fonts, libraries, or other resources. Make it responsive and include subtle animation.",
            Kind.COMPARISON: 'Return only JSON with keys "evens", "sum_of_squares", and "count". List the even integers from 1 through 10 in ascending order, compute the sum of their squares, and count them.',
            Kind.OTHER: "Explain how you would verify a surprising scientific claim. Give concrete steps and distinguish evidence from assumptions.",
        }
    )
    default_expected_json: str = '{"evens":[2,4,6,8,10],"sum_of_squares":220,"count":5}'

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require an IANA time zone usable by the server scheduler."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA time zone.") from exc
        return value


class DomainError(Exception):
    """Carry a safe public error without exposing an upstream secret."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        """Set the machine-readable code and safe client-facing explanation."""
        super().__init__(message)
        self.code = code
        self.status = status


class Challenge(Record):
    """Describe a fixed challenge whose text is versioned with its evaluator."""

    id: str
    name: str
    name_en: str
    expected_count: int
    prompt: str


class RunSummary(Record):
    """Project lightweight history without loading private full output bodies."""

    id: str
    batch_id: str
    group_id: str | None
    target_id: str | None
    account_id: str
    kind: str
    status: Status
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    account_name: str
    model: str
    effort: str
    verdict: str
    score: float | None = None
    review: str | None = None
    error: str | None = None
    elapsed: float = 0
    total_tokens: int | None = None
    preview: str = ""
