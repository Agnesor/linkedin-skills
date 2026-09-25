FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Cloud Build runs a plain `docker build`, so the release URL must be the default.
ARG DATA_URL=https://github.com/Agnesor/linkedin-skills/releases/download/data-v1
COPY data.sha256 ./
COPY scripts/fetch_data.py scripts/
RUN python scripts/fetch_data.py --base-url "$DATA_URL" --dest /app/data --checksums data.sha256

COPY . .

# add_ga.py patches Streamlit's index.html at start-up, so the non-root user must own it.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app /app/.venv/lib/python3.12/site-packages/streamlit/static
USER app

ENV PORT=8080 \
    DATA_DIR=/app/data
EXPOSE 8080

CMD ["sh", "-c", "python add_ga.py; exec streamlit run main.py --server.port=$PORT --server.address=0.0.0.0"]
