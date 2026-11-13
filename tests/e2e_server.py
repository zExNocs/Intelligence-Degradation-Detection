"""Host the production WebUI with deterministic, network-free model fixtures."""

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path

import uvicorn

from intelligence_degradation_detection.bootstrap import create_app
from intelligence_degradation_detection.domain.models import (
    Account,
    AccountInput,
    DomainError,
    GroupInput,
    Kind,
    Output,
    Settings,
    TargetInput,
    Usage,
)

PROJECT = Path(__file__).resolve().parents[1]
VALIDATION = PROJECT.parent / "temp/doc/validation/browser"
HTML = """<!doctype html><html><head><style>
body{margin:0;display:grid;place-items:center;min-height:100vh;background:#edf5ed;color:#1e5448;font-family:system-ui}h1{font-weight:600}svg{width:75%;max-width:500px}main{text-align:center}small{letter-spacing:.2em}
</style></head><body><main><small>A LITTLE MOMENT OF BALANCE</small><h1>The cycling pelican</h1><svg viewBox="0 0 500 270"><path d="M10 250H490" stroke="#a4b5a7"/><g fill="none" stroke="#325d55" stroke-width="5"><circle cx="140" cy="195" r="50"/><circle cx="350" cy="195" r="50"/><path d="M140 195L205 125L260 195H140L190 125H302L350 195M260 195L302 125L292 100H315"/></g><path d="M190 120Q140 80 210 60L260 50Q280 10 305 35L300 70L390 85L300 110Q275 160 190 120" fill="white" stroke="#9caf9f" stroke-width="3"/><path d="M300 70L400 85L300 105" fill="#e6b454"/><circle cx="293" cy="53" r="5"/><path d="M240 135L250 178" stroke="#dba843" stroke-width="5"/></svg><p id="script-status">Waiting for JavaScript</p><button onclick="document.getElementById('script-status').textContent='Interactive preview works'">Try animation</button></main><script>document.getElementById('script-status').textContent='JavaScript is active';</script></body></html>"""


class BrowserGateway:
    """Provide repeatable model results while counting actual invocations."""

    def __init__(self) -> None:
        """Initialize per-process observability without an upstream endpoint."""
        self.invocations = 0

    async def models(self, account: Account) -> list[str]:
        """Return a shared cache fixture for create and edit workflows."""
        return ["fixture-model", "fixture-partial", "fixture-slow"]

    async def invoke(
        self,
        account: Account,
        model: str,
        effort: str,
        prompt: str,
        settings: Settings,
        progress: Callable[[Output], None],
    ) -> Output:
        """Hold slow calls until cancelled and return other fixtures immediately."""
        self.invocations += 1
        if model == "fixture-slow":
            await asyncio.Event().wait()
        if model == "fixture-failure":
            raise DomainError("upstream_unavailable", "Fixture upstream unavailable.")
        text = (
            HTML
            if "pelican" in prompt.lower()
            else prompt
            if prompt.startswith("<!doctype")
            else '{"evens":[2,4,6,8,10],"sum_of_squares":220,"count":5}'
        )
        if model == "fixture-partial" and not text.startswith("<!doctype"):
            text = '{"evens":[2,4,6,8,10],"sum_of_squares":200,"count":5}'
        if model == "fixture-fingerprint":
            text = " ".join(str(1 + index % 355) for index in range(340))
        output = Output(
            text=text,
            usage=Usage(input_tokens=32, output_tokens=86, total_tokens=118),
            elapsed=0.15,
            finish_reason="completed",
        )
        progress(output)
        return output


class BrowserSource:
    """Keep the public demo fixture independent of real account-source services."""

    async def discover(self) -> list[dict[str, object]]:
        """Reject source discovery without sending a network request."""
        raise DomainError(
            "demo_source_disabled", "Account imports are disabled in the local demo."
        )

    async def resolve(self, external_id: int) -> Account:
        """Reject credential resolution even if source settings are entered."""
        raise DomainError(
            "demo_source_disabled", "Account imports are disabled in the local demo."
        )


async def seed(app) -> None:
    """Populate enough aligned batches to exercise responsive history pagination."""
    service, worker = app.state.service, app.state.worker
    accounts = [
        service.save_account(
            AccountInput(
                name=name,
                api_key="fixture-not-a-real-key",
                default_model="fixture-model",
            )
        )
        for name in ("North API", "West API")
    ]
    for name, kind in (
        ("JSON baseline", Kind.COMPARISON),
        ("Pelican studio", Kind.PELICAN),
    ):
        group = await service.save_group(
            GroupInput(
                name=name,
                kind=kind,
                prompt=service.repo.settings().prompts[kind],
                expected_json=service.repo.settings().default_expected_json,
                targets=[
                    TargetInput(
                        account_id=account.id,
                        model="fixture-model" if index == 0 else "fixture-partial",
                    )
                    for index, account in enumerate(accounts)
                ],
            )
        )
        for _ in range(7):
            await service.run_group(group.id)
            await worker.tick()
            await asyncio.gather(*(task for _, task in list(worker.tasks.values())))


if __name__ == "__main__":
    VALIDATION.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="server-", dir=VALIDATION) as directory:
        gateway = BrowserGateway()
        app = create_app(
            Path(directory),
            PROJECT / "resources/web",
            gateway=gateway,
            source=BrowserSource(),
        )
        app.state.auth.rotate("browser-fixture-token-not-a-secret")
        asyncio.run(seed(app))

        @app.get("/api/v1/fixture/calls")
        async def calls() -> dict[str, int]:
            """Expose fixture-only call counts for proving refresh does not execute."""
            return {"calls": gateway.invocations}

        # Register before the static mount, which otherwise matches this test route.
        app.router.routes.insert(0, app.router.routes.pop())
        uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
