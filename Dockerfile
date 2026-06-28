# ILX AI CLI — containerized build
# MIT License — Copyright 2026 ILX Studio

FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency spec first (layer caching)
COPY pyproject.toml README.md LICENSE ./

# Install Python dependencies without the package itself
RUN pip install --no-cache-dir httpx>=0.27 httpx-sse>=0.4 keyring>=25

# Copy source
COPY app/ ./app/
COPY cli/ ./cli/
COPY codex/ ./codex/
COPY main.py ./

# Install the package
RUN pip install --no-cache-dir -e ".[rag]"

# Runtime stage
FROM base AS runtime

# Non-root user for security
RUN useradd -m -u 1000 ilxuser
USER ilxuser
WORKDIR /home/ilxuser

# Config and workspace dirs
RUN mkdir -p /home/ilxuser/.ilx_cli /home/ilxuser/workspace

ENV ILX_NO_BANNER=0
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "main"]
CMD ["--help"]
