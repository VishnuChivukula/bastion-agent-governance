# Bastion: API + gateway + console in one container (ADR-001).
# Reference implementation; not production; not legal advice.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so this layer is reused when only the source changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY demo ./demo
COPY policies ./policies
COPY config ./config
COPY fixtures ./fixtures
COPY knowledge ./knowledge
COPY evals ./evals
COPY scripts ./scripts
COPY Procfile LICENSE ./
RUN uv sync --locked --no-dev

# Run as an unprivileged user; only the data directory is writable.
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin bastion \
    && mkdir -p /app/data /app/.streamlit \
    && chown -R bastion:bastion /app/data /app/.streamlit
USER bastion

# Replay mode by default: no API key, no cost. The console listens on $PORT (set by the
# platform, 8501 otherwise); the API and gateway stay on loopback unless BASTION_API_BIND is set.
ENV BASTION_MODE=replay \
    BASTION_DB_PATH=/app/data/bastion.db \
    BASTION_BIND=0.0.0.0 \
    PORT=8501 \
    HOME=/app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "scripts/smoke.py", "--health-only"]

CMD ["honcho", "start"]
