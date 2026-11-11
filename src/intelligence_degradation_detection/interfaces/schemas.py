"""Define public web contracts that never serialize stored credentials."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..domain.models import Account, Call, GroupInput, Run, RunSummary, Settings, Target


class LoginInput(BaseModel):
    """Accept a token only in a request body, never in a URL."""

    token: str = Field(min_length=1, max_length=512)


class TokenInput(BaseModel):
    """Require enough entropy-bearing room for an operator-provided token."""

    token: str = Field(min_length=24, max_length=512)


class ProxyView(BaseModel):
    """Expose the source route for comparison without authentication secrets."""

    source_id: int | None = None
    name: str | None = None
    protocol: str
    host: str
    port: int
    authenticated: bool


class AccountView(BaseModel):
    """Expose account routing and preferences while withholding all secrets."""

    id: str
    name: str
    protocol: str
    base_url: str
    path: str
    models_path: str
    default_model: str
    default_effort: str
    max_parallel: int
    enabled: bool
    source: str
    external_id: int | None
    account_type: str
    source_active: bool
    source_error: str | None
    synced_at: float | None
    last_model: str | None
    last_effort: str | None
    models: list[str]
    models_at: float | None
    models_error: str | None
    has_key: bool
    has_headers: bool
    has_proxy: bool
    proxy: ProxyView | None = None

    @classmethod
    def from_account(cls, account: Account) -> "AccountView":
        """Construct the view from an explicit allowlist of public fields."""
        proxy = account.credentials.proxy
        return cls.model_validate(
            {
                **account.model_dump(exclude={"config", "credentials"}),
                **account.config.model_dump(exclude={"api_key", "headers"}),
                "has_key": bool(
                    account.credentials.api_key or account.credentials.access_token
                ),
                "has_headers": bool(account.credentials.headers),
                "has_proxy": account.credentials.proxy is not None,
                "proxy": ProxyView(
                    source_id=account.source_proxy_id,
                    name=account.source_proxy_name,
                    protocol=proxy.protocol,
                    host=proxy.host,
                    port=proxy.port,
                    authenticated=bool(proxy.username or proxy.password),
                )
                if proxy
                else None,
            }
        )


class GroupView(BaseModel):
    """Expose group configuration and stable per-account check identities."""

    id: str
    recipe: GroupInput
    revision: int
    next_run_at: float | None
    targets: list[Target]
    active_runs: dict[str, str] = Field(default_factory=dict)


class HistoryPage(BaseModel):
    """Page aligned execution batches without returning full output bodies."""

    batches: list[str]
    runs: list[RunSummary]
    has_more: bool
    total_batches: int


class RunDetail(Run):
    """Expose the immutable recipe and each individual invocation result."""

    calls: list[Call]


class ReviewInput(BaseModel):
    """Set or clear a human judgment with an optional explanation."""

    verdict: Literal["pass", "fail"] | None = None
    note: str = Field(default="", max_length=2000)


class ImportInput(BaseModel):
    """Select explicit source account identifiers for import."""

    ids: list[int] = Field(min_length=1, max_length=100)


class CronInput(BaseModel):
    """Preview a schedule before persisting it."""

    expression: str
    timezone: str

    @field_validator("timezone")
    @classmethod
    def validate_zone(cls, value: str) -> str:
        """Return a validated zone so bad previews become field errors."""
        return Settings.validate_timezone(value)


class SettingsView(Settings):
    """Omit the source administrator key from every settings response."""

    sub2api_key: str = Field(default="", exclude=True)
    has_sub2api_key: bool = False


class SettingsInput(Settings):
    """Retain an existing administrator key when the field is omitted."""

    sub2api_key: str = ""


class DashboardView(BaseModel):
    """Separate quality, attribution, manual findings, and operational errors."""

    account_count: int
    check_count: int
    runs_24h: int
    completed_24h: int
    total_tokens: int
    unknown_usage_count: int
    average_seconds: float | None
    success_rate: float | None
    alerts: dict[str, list[RunSummary]]
