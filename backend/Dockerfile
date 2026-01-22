# ==============================================================================
# Modular File Manager - FastAPI Backend Dockerfile
# ==============================================================================
# Multi-stage build for optimized production image
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies
# ------------------------------------------------------------------------------
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS builder

# Build arguments
ARG BUILD_DATE
ARG VERSION=1.0.0

# Metadata
LABEL maintainer="File Manager Team"
LABEL version="${VERSION}"
LABEL description="FastAPI backend for Modular File Manager"
LABEL build-date="${BUILD_DATE}"

# Set environment variables for build
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
WORKDIR /build
COPY backend/requirements.txt .

# Install dependencies in virtual environment
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Runtime - Create final image
# ------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/backend:$PYTHONPATH"

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    openssl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Create application user (non-root for security)
RUN groupadd -r filemanager && \
    useradd -r -g filemanager -u 1000 -m -s /sbin/nologin filemanager

# Create application directories
RUN mkdir -p /app/backend \
    /var/log/file-manager \
    /etc/file-manager \
    /etc/ssl/file-manager \
    /etc/ssl/certs \
    /etc/ssl/private && \
    chown -R filemanager:filemanager /app \
    /var/log/file-manager \
    /etc/file-manager \
    /etc/ssl/file-manager

# Set working directory
WORKDIR /app

# Copy backend application code
COPY --chown=filemanager:filemanager backend/ /app/backend/

# Copy entrypoint script
COPY --chown=filemanager:filemanager backend/entrypoint.sh /app/entrypoint.sh

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Install pg_isready for health checks
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Switch to non-root user
USER filemanager

# Expose ports
EXPOSE 8000
EXPOSE 8443

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# ==============================================================================
# Build Instructions:
# ==============================================================================
# docker build -f Dockerfile.api -t file-manager-api:latest .
# docker run -p 8000:8000 --env-file .env file-manager-api:latest
# ==============================================================================
