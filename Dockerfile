# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Omni-Localizer (OL) production image.
# Multi-stage build:
#   1. `builder`  - resolves the locked dependency graph via `uv sync`
#                   into a project-local `.venv` we can COPY to runtime.
#   2. `runtime`  - minimal python:3.13-slim with the prepared venv only.
# ---------------------------------------------------------------------------

# ---------- Stage 1: dependency resolution ---------------------------------
FROM python:3.13-slim AS builder

# Install uv from the official GHCR image (pinned tag, no network surprises).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy only the metadata files first so the dependency layer is cache-friendly.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Install the full project (runtime + all extras) into the project-local venv.
# `--frozen` refuses to mutate uv.lock; `--no-dev` keeps the image lean.
RUN uv sync --frozen --all-extras --no-dev

# ---------- Stage 2: runtime image -----------------------------------------
FROM python:3.13-slim AS runtime

WORKDIR /app

# Pull the resolved project (source + venv + metadata) from the builder.
COPY --from=builder /app /app

# Make the project venv the first PATH entry so `ol` / `ol-mcp` are on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The CLI entrypoint is registered in pyproject.toml under [project.scripts].
ENTRYPOINT ["ol"]
CMD ["--help"]
