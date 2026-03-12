#!/bin/bash
# Build and redeploy only the frontend pod.
# Run from NAGA-open-webui/ directory.
# Usage: ./build-frontend.sh

set -e

IMAGE_NAME="open-webui-frontend"
IMAGE_TAG="latest"
NAMESPACE="open-webui"
DEPLOYMENT="open-webui-frontend-deployment"

echo "▶ Building frontend Docker image..."
docker build \
  -f Dockerfile.frontend \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  .

echo "▶ Restarting frontend pod..."
kubectl rollout restart deployment/${DEPLOYMENT} -n ${NAMESPACE}

echo "▶ Waiting for rollout..."
kubectl rollout status deployment/${DEPLOYMENT} -n ${NAMESPACE}

echo "✓ Frontend deployed. Access at http://localhost:30080"
