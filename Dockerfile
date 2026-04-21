# MediaCrawler Docker Image
# Multi-stage build for production deployment

# ============================================================
# Stage 1: Build dependencies
# ============================================================
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /build

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install Python dependencies (without dev groups)
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --frozen

# ============================================================
# Stage 2: Runtime
# ============================================================
FROM python:3.11-slim AS runtime

LABEL maintainer="MediaCrawler"
LABEL description="Multi-platform social media crawler with Docker support"

# Install runtime dependencies: Node.js + Playwright system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    # Node.js 20.x LTS
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    # Playwright Chromium system dependencies
    && apt-get install -y --no-install-recommends \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        libatspi2.0-0 \
        fonts-liberation \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Create non-root user
RUN groupadd -r crawler && useradd -r -g crawler -m -d /home/crawler crawler

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /build/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install Playwright browsers with system deps
# (system deps already installed above, this just downloads chromium)
RUN uv run playwright install chromium

# Copy application code
COPY --chown=crawler:crawler . /app

# Create data directory
RUN mkdir -p /app/data /app/browser_data /app/data/.checkpoint \
    && chown -R crawler:crawler /app/data /app/browser_data

# Switch to non-root user
USER crawler

# Volumes for persistent data
VOLUME ["/app/data", "/app/browser_data"]

# Health check (only useful when running API server)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# Default entrypoint - run crawler
# Override with: docker run mediacrawler uv run python main.py --platform xhs --type search
ENTRYPOINT ["uv", "run", "python"]
CMD ["main.py"]
