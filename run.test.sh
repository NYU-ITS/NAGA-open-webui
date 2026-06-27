#!/bin/bash
# run.test.sh — Build and run test image based on open-webui:latest
# Not tracked by git (see .git/info/exclude)
#
# Usage:
#   ./run.test.sh                         # Build test image and start container
#   ./run.test.sh --build                 # Force rebuild test image
#   ./run.test.sh exec <cmd>              # Run command in running test container
#   ./run.test.sh stop                    # Stop test container
#   ./run.test.sh logs                    # Follow logs

set -euo pipefail

IMAGE_NAME="open-webui-test"
CONTAINER_NAME="open-webui-test"
HOST_PORT=3001
CONTAINER_PORT=8080

build_image() {
    echo "==> Building test image: ${IMAGE_NAME}"
    docker build -t "${IMAGE_NAME}" -f Dockerfile.test .
    echo "==> Build complete"
}

run_container() {
    echo "==> Starting test container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}" &>/dev/null || true
    docker rm "${CONTAINER_NAME}" &>/dev/null || true

    # Mount tests/ dir for live editing, mount data volume for persistence
    docker run -d -p "${HOST_PORT}:${CONTAINER_PORT}" \
        --add-host=host.docker.internal:host-gateway \
        -v "${IMAGE_NAME}:/app/backend/data" \
        -v "$(pwd)/tests:/app/tests" \
        -v "$(pwd)/src:/app/src:ro" \
        -v "$(pwd)/svelte.config.js:/app/svelte.config.js:ro" \
        -v "$(pwd)/vite.config.ts:/app/vite.config.ts:ro" \
        -v "$(pwd)/tsconfig.json:/app/tsconfig.json:ro" \
        --name "${CONTAINER_NAME}" \
        --restart no \
        "${IMAGE_NAME}" bash -c '
set -e
cd /app/backend
# Pre-init DB to avoid config table error at startup
export WEBUI_SECRET_KEY="test-secret"
export SUPER_ADMIN_EMAILS="admin@test.com"
export WEBUI_URL="http://localhost:3001"
export E2E_BASE_URL="http://localhost:8080"
export E2E_ADMIN_EMAIL="admin@test.com"
export E2E_ADMIN_PASSWORD="changeme-e2e-admin"
export E2E_USER_EMAIL="e2e-user@example.test"
export E2E_USER_PASSWORD="changeme-e2e-user"
PYTHONPATH=/app/backend python -c "
import os
os.environ.setdefault(\"WEBUI_SECRET_KEY\", \"test-secret\")
os.environ.setdefault(\"SUPER_ADMIN_EMAILS\", \"admin@test.com\")
from open_webui.internal.db import engine, Base
Base.metadata.create_all(bind=engine)
print(\"DB initialized with all tables\")
" 2>&1
exec bash /app/backend/start.sh
'

    echo "==> Container started at http://localhost:${HOST_PORT}"
    echo "==> Run tests: docker exec -w /app ${CONTAINER_NAME} <command>"
}

case "${1:-}" in
    --build)
        build_image
        run_container
        ;;
    exec)
        shift
        if [ $# -eq 0 ]; then
            echo "Usage: $0 exec <command>"
            exit 1
        fi
        docker exec -w /app "${CONTAINER_NAME}" "$@"
        ;;
    stop)
        echo "==> Stopping container: ${CONTAINER_NAME}"
        docker stop "${CONTAINER_NAME}" &>/dev/null || true
        docker rm "${CONTAINER_NAME}" &>/dev/null || true
        ;;
    logs)
        docker logs -f "${CONTAINER_NAME}"
        ;;
    *)
        build_image
        run_container
        ;;
esac
