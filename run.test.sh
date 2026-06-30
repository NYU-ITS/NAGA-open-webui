#!/bin/bash
# run.test.sh — Build and run test image based on open-webui:latest
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
    # Ensure base image exists locally
    if ! docker image inspect open-webui:latest &>/dev/null; then
        echo "==> Base image open-webui:latest not found — building from Dockerfile"
        docker build -t open-webui:latest -f Dockerfile .
    fi
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
        --env-file .env.test \
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
PYTHONPATH=/app/backend python -c "
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
