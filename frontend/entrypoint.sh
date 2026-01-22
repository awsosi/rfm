#!/bin/bash
set -e

echo "========================================"
echo "Modular File Manager - WebUI Starting"
echo "========================================"

# Wait for API to be ready
echo "[INFO] Waiting for API backend..."
API_HOST=$(echo "${API_URL}" | sed -E 's|https?://([^:]+):.*|\1|')
API_PORT=$(echo "${API_URL}" | sed -E 's|https?://[^:]+:([0-9]+).*|\1|')

# Default to port 8000 if parsing fails
if [ -z "$API_PORT" ] || [ "$API_PORT" = "$API_URL" ]; then
    API_PORT=8000
fi

until timeout 2 bash -c "cat < /dev/null > /dev/tcp/${API_HOST}/${API_PORT}" >/dev/null 2>&1; do
    echo "[INFO] API is unavailable - sleeping"
    sleep 2
done
echo "[INFO] API is up and running"

# Start WebUI server
echo "[INFO] Starting WebUI server..."
echo "========================================"
echo "WebUI URL: http://0.0.0.0:${WEBUI_PORT:-3000}"
echo "Health Check: http://0.0.0.0:${WEBUI_PORT:-3000}/health"
echo "API Backend: ${API_URL}"
echo "========================================"

# Use gunicorn for production
exec gunicorn server:app \
    --bind "${WEBUI_HOST:-0.0.0.0}:${WEBUI_PORT:-3000}" \
    --workers 2 \
    --threads 4 \
    --worker-class sync \
    --timeout 120 \
    --keep-alive 5 \
    --log-level "${LOG_LEVEL:-info}" \
    --access-logfile - \
    --error-logfile -
