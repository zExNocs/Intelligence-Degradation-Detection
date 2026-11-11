"""Compose infrastructure once and host the authenticated web application."""

import os
import re
import secrets
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from starlette.middleware.base import RequestResponseEndpoint

from . import __version__
from .adapters.auth import TokenAuth
from .adapters.gateway import CODEX_CATALOGUE_VERSION, HttpModelGateway
from .adapters.modeltrace import ModelTraceEvaluator
from .adapters.storage import SQLiteRepository
from .adapters.sub2api import Sub2APISource
from .application.ports import AccountSource, ModelGateway
from .application.service import EvaluationService
from .application.worker import Worker
from .domain.models import DomainError
from .interfaces.http import api_router
from .interfaces.schemas import LoginInput, TokenInput

PARENT_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-src blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)


def create_app(
    data_dir: Path | None = None,
    web_dir: Path | None = None,
    gateway: ModelGateway | None = None,
    source: AccountSource | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Build a single-instance app with replaceable network boundaries for tests."""
    root_path = os.environ.get("IDD_ROOT_PATH", "").rstrip("/")
    if root_path and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", root_path):
        raise ValueError(
            "IDD_ROOT_PATH must contain only slash-separated path segments."
        )
    cookie_path = root_path + "/"
    resources = Path(__file__).resolve().parents[2] / "resources"
    data_dir = (
        data_dir or Path(os.environ.get("IDD_DATA_DIR", resources / "data"))
    ).resolve()
    web_dir = (
        web_dir or Path(os.environ.get("IDD_WEB_DIR", resources / "web"))
    ).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    repository = SQLiteRepository(data_dir / "idd.sqlite3")
    try:
        auth = TokenAuth(data_dir / "yaml/auth.yaml")
    except Exception:
        repository.close()
        raise
    source = source or Sub2APISource(repository.settings)
    service = EvaluationService(
        repository,
        gateway
        or HttpModelGateway(
            ca_bundle=os.environ.get("IDD_CA_BUNDLE"),
            codex_client_version=os.environ.get(
                "IDD_CODEX_CLIENT_VERSION", CODEX_CATALOGUE_VERSION
            ),
        ),
        source,
        ModelTraceEvaluator(),
    )
    worker = Worker(service)
    preview_nonce = secrets.token_urlsafe(32)
    browser_policy = PARENT_CSP.replace(
        "script-src 'self'",
        f"script-src 'self' 'nonce-{preview_nonce}'; script-src-attr 'unsafe-inline'",
    )
    instance_lock = FileLock(data_dir / "server.lock", timeout=0)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own the scheduler, process lock, and storage for exactly one lifespan."""
        try:
            instance_lock.acquire()
        except Timeout as exc:
            repository.close()
            raise RuntimeError(
                "Another instance already owns this data directory."
            ) from exc
        try:
            if start_worker:
                await worker.start()
            yield
        finally:
            await worker.stop()
            repository.close()
            instance_lock.release()

    app = FastAPI(
        root_path=root_path,
        title="Intelligence Degradation Detection",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.service, app.state.worker, app.state.auth = service, worker, auth
    login_attempts: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def protect(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Gate private endpoints and apply both origin and browser containment rules."""
        path = request.url.path
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path) :]
        if path.startswith("/api/v1"):
            origin = request.headers.get("origin")
            allowed = {
                item
                for item in os.environ.get("IDD_ALLOWED_ORIGINS", "").split(",")
                if item
            }
            if (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and origin
                and urlsplit(origin).netloc != request.url.netloc
                and origin not in allowed
            ):
                return JSONResponse(
                    {
                        "code": "origin_rejected",
                        "message": "The request origin is not allowed.",
                    },
                    status_code=403,
                )
            is_login = path == "/api/v1/auth/session" and request.method == "POST"
            if not is_login and not auth.verify(request.cookies.get("idd_session")):
                return JSONResponse(
                    {"code": "unauthorized", "message": "An access token is required."},
                    status_code=401,
                )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = browser_policy
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        """Map known errors without adding a second log or exposing private state."""
        return JSONResponse(
            {"code": error.code, "message": str(error)}, status_code=error.status
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Omit rejected input values so credentials cannot echo in validation errors."""
        return JSONResponse(
            {
                "code": "validation_error",
                "message": "Invalid request fields.",
                "fields": [
                    ".".join(map(str, entry["loc"])) for entry in error.errors()
                ],
            },
            status_code=422,
        )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        """Expose process liveness without private account or model metadata."""
        return {"status": "ok"}

    @app.post("/api/v1/auth/session")
    async def login(
        value: LoginInput, request: Request, response: Response
    ) -> dict[str, bool]:
        """Exchange a valid access token for a revocable HttpOnly session."""
        peer = request.client.host if request.client else "unknown"
        attempts = login_attempts[peer]
        now = time.monotonic()
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 20:
            raise DomainError(
                "login_limited", "Too many attempts; wait one minute.", 429
            )
        attempts.append(now)
        session = auth.login(value.token)
        attempts.clear()
        response.set_cookie(
            "idd_session",
            session,
            httponly=True,
            secure=request.url.scheme == "https"
            or os.environ.get("IDD_SECURE_COOKIE") == "1",
            samesite="strict",
            max_age=7 * 86400,
            path=cookie_path,
        )
        return {"authenticated": True}

    @app.get("/api/v1/auth/session")
    async def session() -> dict[str, bool]:
        """Let the app check session validity without requesting model data."""
        return {"authenticated": True}

    @app.get("/api/v1/preview-policy")
    async def preview_policy() -> dict[str, str]:
        """Permit trusted preview construction without relaxing host script elements.

        Blob documents inherit the host policy. Their additional policy and opaque
        iframe sandbox constrain these scripts to the preview document.
        """
        return {"nonce": preview_nonce}

    @app.delete("/api/v1/auth/session", status_code=204)
    async def logout(response: Response) -> None:
        """Remove the browser session cookie."""
        response.delete_cookie("idd_session", path=cookie_path)

    @app.put("/api/v1/auth/token")
    async def rotate(value: TokenInput, response: Response) -> dict[str, bool]:
        """Persist a new operator token and revoke all previous sessions."""
        auth.rotate(value.token)
        response.delete_cookie("idd_session", path=cookie_path)
        return {"reauthenticate": True}

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    async def openapi() -> dict:
        """Serve the same contract used to generate frontend API types."""
        return app.openapi()

    app.include_router(api_router(service, worker))
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        async def frontend_missing() -> JSONResponse:
            """Explain the missing development build without claiming a usable UI."""
            return JSONResponse(
                {"message": "Build the WebUI first; see the project README."},
                status_code=503,
            )

    return app
