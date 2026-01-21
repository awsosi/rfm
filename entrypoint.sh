#!/bin/bash
set -e

echo "========================================"
echo "Modular File Manager - API Starting"
echo "========================================"

# Generate self-signed SSL certificate if TLS is enabled and cert doesn't exist
if [ "${TLS_ENABLED}" = "true" ] && [ ! -f "/etc/ssl/certs/filemanager.crt" ]; then
    echo "[INFO] Generating self-signed SSL certificate..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/ssl/private/filemanager.key \
        -out /etc/ssl/certs/filemanager.crt \
        -subj "/C=US/ST=State/L=City/O=Organization/OU=IT/CN=filemanager.local" \
        2>/dev/null
    echo "[INFO] SSL certificate generated successfully"
fi

# Wait for PostgreSQL to be ready
echo "[INFO] Waiting for PostgreSQL..."
until pg_isready -h postgres -U "${POSTGRES_USER:-filemanager}" >/dev/null 2>&1; do
    echo "[INFO] PostgreSQL is unavailable - sleeping"
    sleep 2
done
echo "[INFO] PostgreSQL is up and running"

# Wait for Redis to be ready
echo "[INFO] Waiting for Redis..."
until timeout 2 bash -c "cat < /dev/null > /dev/tcp/redis/6379" >/dev/null 2>&1; do
    echo "[INFO] Redis is unavailable - sleeping"
    sleep 2
done
echo "[INFO] Redis is up and running"

# Run database migrations
echo "[INFO] Running database migrations..."
cd /app/backend
alembic upgrade head || {
    echo "[ERROR] Database migration failed"
    exit 1
}
echo "[INFO] Database migrations completed successfully"

# Start API server
echo "[INFO] Starting FastAPI server..."
echo "========================================"
echo "API URL: http://0.0.0.0:8000"
echo "Health Check: http://0.0.0.0:8000/health"
if [ "${TLS_ENABLED}" = "true" ]; then
    echo "HTTPS URL: https://0.0.0.0:8443"
fi
echo "========================================"

exec python -m uvicorn api.app:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --workers "${API_WORKERS:-4}" \
    --log-level "${LOG_LEVEL:-info}" \
    --access-log \
    --use-colors \
    ${TLS_ENABLED:+--ssl-keyfile /etc/ssl/private/filemanager.key} \
    ${TLS_ENABLED:+--ssl-certfile /etc/ssl/certs/filemanager.crt}
