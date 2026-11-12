# TravelMate web server for a public deployment (Render, Fly, any Docker host).
# Build:  docker build -t travelmate travelmate
# Run:    docker run -p 8000:8000 --env-file travelmate/.env travelmate
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1

# Dependencies first, so code changes reuse this layer. MAF is the agent engine; psycopg talks to PostgreSQL.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra maf --extra postgres

COPY app ./app
COPY frontend ./frontend

RUN useradd --create-home --uid 10001 travelmate && chown -R travelmate /app
USER travelmate
ENV PATH="/app/.venv/bin:$PATH" \
    TRAVELMATE_MODE=live \
    AGENT_ENGINE=maf \
    TRAVELMATE_ORCHESTRATOR=planning \
    TRAVELMATE_PLACE_PROVIDER=open_data

EXPOSE 8000
# The host's proxy terminates HTTPS: trust its X-Forwarded-* headers so cookies are Secure
# and sign-in throttling sees the visitor's address, not the proxy's. PORT is set by the host.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
