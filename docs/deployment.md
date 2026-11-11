# Deployment and development

All commands in this document start in the repository root containing `compose.yaml` unless noted otherwise. Python 3.13 and Node 24 are the local toolchain. Production runs one application process, including the scheduler. For a network-free local preview with synthetic data, see [the demo](demo.md).

## Docker

```sh
docker compose up --build -d
docker compose ps
docker compose exec idd cat /app/resources/data/yaml/auth.yaml
```

Open http://localhost:8000. Read `access_token` privately and enter it at login. Do not paste the YAML into logs, issues, or screenshots. A missing file is created once; a damaged or unwritable existing file fails explicitly. Token changes in Settings revoke all sessions.

The multi-stage Dockerfile builds frontend assets with Node and installs the Python wheel plus hashed production dependencies into Python 3.13 slim. The runtime uses UID/GID 10001, one Uvicorn process, dropped Linux capabilities, and a `/healthz` liveness check. The named `idd-data` volume owns `/app/resources/data`, including SQLite/WAL files and `yaml/auth.yaml`. Container recreation preserves it. Do not use `docker compose down -v` unless you intend to delete all application data.

The default host binding is `127.0.0.1:8000`. For remote users, put the service behind an HTTPS reverse proxy and configure `IDD_SECURE_COOKIE=1`. Preserve the public Host header; when necessary, set `IDD_ALLOWED_ORIGINS` to the exact public HTTPS origin. Run only one replica per data directory; SQLite and the scheduler are not configured for distributed workers.

| Environment variable | Meaning |
| --- | --- |
| `IDD_DATA_DIR` | Absolute persistent data directory |
| `IDD_WEB_DIR` | Absolute directory containing built `index.html` and assets |
| `IDD_ROOT_PATH` | Optional public URL prefix, such as `/evaluation`; omit the trailing slash |
| `TZ` | Initial IANA timezone; subsequent changes use application Settings |
| `IDD_SECURE_COOKIE=1` | Require HTTPS for session-cookie transmission behind TLS termination |
| `IDD_ALLOWED_ORIGINS` | Comma-separated exact extra allowed mutation origins |
| `IDD_CA_BUNDLE` | Optional trusted CA PEM file for model HTTPS requests; verification remains enabled |
| `IDD_CODEX_CLIENT_VERSION` | Codex OAuth catalogue compatibility version (default `0.165.0`); override with a verified compatible client version if the upstream changes its minimum-version filtering |

Outbound environment proxy variables are intentionally ignored. Direct API accounts use their configured route; imported accounts use their authoritative sub2api proxy. A proxy error is surfaced without direct fallback. Credentials and raw evidence are persisted in the data volume, so restrict access and backups to its operators.

For a consistent backup, stop the service and copy the complete mounted data directory/volume. Restore it before starting the same application version. Alembic upgrades run on application construction; keep a pre-upgrade backup. Restore that backup when rolling back across an incompatible schema migration rather than pointing older code at a newer database. Interrupted model calls are retained and never retried automatically; queued work is recovered.

The frontend uses relative asset and API URLs, so the same image supports root or subpath deployment. For a subpath, set `IDD_ROOT_PATH`, redirect the bare prefix to its trailing-slash form, and have the reverse proxy strip that prefix before forwarding. Session cookies are restricted to the configured prefix. Keep deployment-specific addresses, credentials, Compose overrides, runtime data, and backups outside the project source tree.

## Reverse proxy example

For an existing HTTPS Nginx virtual host serving `/evaluation/`, copy `.env.example` to `.env`, set `IDD_ROOT_PATH=/evaluation` and `IDD_SECURE_COOKIE=1`, and recreate the application with `docker compose up --build -d`. Keep the application port bound to loopback. Add these generic locations inside that virtual host:

```nginx
location = /evaluation {
    return 308 /evaluation/;
}

location /evaluation/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
    proxy_buffering off;
}
```

The trailing slash on `proxy_pass` strips the public prefix; the browser keeps `/evaluation/` in asset/API URLs and the cookie path. TLS certificates and public hostnames belong to the operator's configuration outside this repository. Test Nginx configuration before reloading it. A reverse proxy running in another container needs its own reachable application service address instead of loopback.

若部署到已有 HTTPS Nginx 站点的 `/evaluation/` 下，设置上述两个环境变量，并使用示例转发规则。`proxy_pass` 末尾的斜杠用于去除转发前缀；证书、域名及其他实机配置由部署者在仓库外维护。代理本身若在容器中运行，需使用可达的应用服务地址，不能照搬宿主机回环地址。

## Manual sub2api connection

This integration requires a **sub2api administrator API key**, not a normal model-client key or the administrator password. Create a dedicated key in the source server's administrator-key settings. Restrict allowed source addresses to the actual application network; do not copy network ranges from another installation. Prefer a key that grants only account reads and credential/proxy export when the source supports such a scope. Some source versions expose only redacted account reads as a limited permission and reserve credential export for full administrators. A full-access key is broader than this application's read-only behavior and must be explicitly approved by the operator.

In this application's **Settings → Source connection**, enter the source service root, the administrator key, and the sync interval. The service root excludes `/api/v1` and the model protocol's `/v1` suffix. If using a reverse-proxy prefix, include that prefix; if containers share a network, the service's internal URL may be used. Save, then open **Models → Add account → Import from sub2api**, load the source account list, and select the intended accounts.

Discovery, import, and synchronization read source data without generating model output. Probes and evaluation runs consume model tokens. If listing works but import returns HTTP 403, check the key's permission for credential export; do not silently grant broader access or change source accounts to work around it. Store source keys only in the application's protected runtime data directory. Revoke the dedicated key when removing the integration.

After importing, edit each account, refresh the catalogue or enter an exact model identifier, and save the default model and reasoning effort. Imported accounts deliberately have no assumed default model. The **Choose a model to probe** button opens this editor; after saving a model, it becomes **Probe connection**.

The account card shows the source account ID, assigned proxy ID/name, protocol, host, port, authentication presence, and last successful source sync. Compare these with the account's proxy assignment in sub2api. **Verify source route** fetches the current source bundle and updates this display without generating model output. It verifies the configured route, not the proxy's exit IP or reachability. Catalogue reads and model calls use the freshly resolved proxy with environment proxies disabled; a source or proxy failure never triggers direct fallback. Proxy usernames and passwords are never returned to the browser.

For imported OpenAI OAuth accounts, the Codex catalogue request includes a `client_version` compatibility parameter, configurable through `IDD_CODEX_CLIENT_VERSION`. The upstream filters its catalogue by client version, so HTTP 200 alone does not establish that the expected user models are available. The selector excludes entries explicitly marked hidden; a catalogue containing only hidden entries reports an error. API-key catalogues keep their configured paths and parameters. Catalogue errors show a bounded, credential-redacted upstream reason, and failed refreshes preserve the previous cache. Imported-account refreshes inside the editor also update the shared cache immediately. Refresh saved account catalogues after changing the compatibility version.

## Local development

Use `uv` with the checked-in lock:

```sh
uv sync --frozen --extra dev --python 3.13
cd src/web
npm ci
npm run build
cd ../..
uv run idd
```

Alternatively create a Python 3.13 virtual environment, activate it, and install hashed runtime dependencies followed by the project:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
```

On Windows PowerShell use `py -3.13 -m venv .venv` and `.venv\Scripts\Activate.ps1`. Build the frontend as above, then run `idd`. Editable development defaults to `resources/data` and `resources/web` under the repository root regardless of the shell's launch directory. A separately installed wheel should be launched with explicit absolute `--data-dir` and `--web-dir` paths. The wheel contains backend/migrations/ModelTrace; the frontend build is distributed alongside it or in the Docker image.

For Vite hot reload, run `idd` on port 8000 and `npm run dev` from `src/web` on port 5173. Set `IDD_ALLOWED_ORIGINS=http://127.0.0.1:5173` on the backend first. Use the backend-served production build when checking CSP and generated HTML isolation.

## Checks and dependency updates

```sh
uv run pytest -q
uv run ruff check src/intelligence_degradation_detection tests
uv run mypy
cd src/web
npm run build
npx playwright install chromium
npm run test:e2e
```

The browser fixture starts an isolated loopback server using synthetic accounts and outputs. No real provider credentials are needed. It creates temporary browser files in `../temp/doc/validation/browser/`, outside the repository root. `PLAYWRIGHT_BROWSERS_PATH` may point at an existing local browser installation. Python tests use temporary databases; do not run them against production data.

`pyproject.toml` defines dependency intent; `uv.lock` resolves it and `requirements.lock` is the generated production export. Update them together with `uv lock` and `uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock`. Frontend dependencies use `package-lock.json`; use `npm ci` for reproducible builds. Re-run the targeted protocol, fingerprint, and browser contracts after dependency changes.

To update API types, export `create_app(..., start_worker=False).openapi()` to `resources/openapi.json` using a temporary data directory, close its repository, then run `npm run generate:api` from `src/web`. Run real-provider integration checks separately from the normal fixture-based tests.
