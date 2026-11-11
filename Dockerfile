FROM node:24-bookworm-slim AS web
WORKDIR /build/src/web
COPY src/web/package.json src/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY src/web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS python-build
WORKDIR /build
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY src/intelligence_degradation_detection/ ./src/intelligence_degradation_detection/
COPY threeparty/ ./threeparty/
RUN pip wheel --no-cache-dir --no-deps --wheel-dir=/wheels . \
    && pip install --no-cache-dir --no-deps --prefix=/install /wheels/*.whl

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IDD_DATA_DIR=/app/resources/data \
    IDD_WEB_DIR=/app/resources/web \
    TZ=UTC
WORKDIR /app
RUN groupadd --system --gid 10001 idd \
    && useradd --system --uid 10001 --gid 10001 --create-home idd \
    && mkdir -p /app/resources/data \
    && chown -R idd:idd /app
COPY --from=python-build /install/ /usr/local/
COPY --from=web /build/resources/web/ /app/resources/web/
USER 10001:10001
EXPOSE 8000
VOLUME ["/app/resources/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).close()"]
ENTRYPOINT ["idd", "--host", "0.0.0.0", "--port", "8000"]
