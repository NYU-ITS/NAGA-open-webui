#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-rit-genai-naga-dev}"
APP_BUILD_CONFIG="${APP_BUILD_CONFIG:-open-webui}"
QUALITY_BUILD_CONFIG="${QUALITY_BUILD_CONFIG:-ai-tutor-frontend-quality-checks}"
STATEFULSET="${STATEFULSET:-open-webui}"

echo "Building frontend quality-check image: ${QUALITY_BUILD_CONFIG}"
oc start-build "${QUALITY_BUILD_CONFIG}" --follow --wait -n "${NAMESPACE}"

echo "Building frontend application image: ${APP_BUILD_CONFIG}"
oc start-build "${APP_BUILD_CONFIG}" --follow --wait -n "${NAMESPACE}"

echo "Restarting frontend StatefulSet so it pulls the newly built image: ${STATEFULSET}"
oc rollout restart "statefulset/${STATEFULSET}" -n "${NAMESPACE}"
oc rollout status "statefulset/${STATEFULSET}" -n "${NAMESPACE}" --timeout=1200s

echo "Running frontend post-deployment quality check"
bash scripts/run_post_deploy_frontend_quality_check.sh
