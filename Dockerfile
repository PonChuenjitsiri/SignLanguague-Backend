# syntax=docker/dockerfile:1

# Stage 1: Build the environment with uv
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# Install only the absolute minimum required to compile wheel dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Precompile python files to pyc for faster startup
ENV UV_COMPILE_BYTECODE=1
# Do not create virtualenv since we will install system-wide in builder
ENV UV_PROJECT_ENVIRONMENT=/usr/local

# Copy only dependency definitions first
COPY pyproject.toml ./

# Install dependencies using cache mounts. 
# --no-dev: don't install matplotlib/seaborn
# --no-install-project: don't install the app code itself yet
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

# Stage 2: Final minimal runtime image
FROM python:3.11-slim-bookworm

WORKDIR /app

# Only install libgomp1 which XGBoost requires at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the globally installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app code
COPY . .

# Optimization flags
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTAPI_ENV=production

# Expose port
EXPOSE 8080

RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]