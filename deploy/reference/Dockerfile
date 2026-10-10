# Use Docker's official ECR publication to avoid shared Docker Hub pull quotas.
FROM public.ecr.aws/docker/library/python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_CACHE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY deploy/observability/requirements.txt /tmp/observability-requirements.txt
COPY scripts/observability/run_with_otel.py scripts/observability/operator_metrics_collector.py \
    /app/scripts/observability/
COPY alembic.ini ./
ARG REQUEST_ENGINE_ENABLE_OBSERVABILITY=0
RUN uv sync --frozen --no-dev \
    && case "$REQUEST_ENGINE_ENABLE_OBSERVABILITY" in \
        0) ;; \
        1) uv pip install --python /app/.venv/bin/python -r /tmp/observability-requirements.txt ;; \
        *) echo "REQUEST_ENGINE_ENABLE_OBSERVABILITY must be 0 or 1" >&2; exit 1 ;; \
    esac \
    && useradd --create-home --uid 10001 request-engine \
    && chown -R request-engine:request-engine /app
USER request-engine
ENTRYPOINT []
CMD ["uvicorn", "request_engine.bootstrap.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
