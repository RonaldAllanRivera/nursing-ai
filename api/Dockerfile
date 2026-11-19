FROM python:3.15-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY core/pyproject.toml core/pyproject.toml
COPY core/src core/src
COPY api/pyproject.toml api/pyproject.toml
COPY api/src api/src
COPY mcp/pyproject.toml mcp/pyproject.toml
COPY evals/pyproject.toml evals/pyproject.toml
RUN uv sync --locked --no-dev --package nursing-api

FROM python:3.15-slim-bookworm
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0@sha256:17cfd08eff1dfea3f6a9a1e9c65fdac80aa4919b6085e746615530f43f57d2f1 /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
CMD ["uvicorn", "--factory", "nursing_api.app:create_app", "--host", "0.0.0.0", "--port", "8080"]
