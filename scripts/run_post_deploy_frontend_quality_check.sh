#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-rit-genai-naga-dev}"
WORKLOAD_TYPE="${WORKLOAD_TYPE:-statefulset}"
WORKLOAD_NAME="${WORKLOAD_NAME:-open-webui}"
JOB_NAME="${JOB_NAME:-ai-tutor-frontend-post-deploy-quality-check}"
TIMEOUT="${TIMEOUT:-900s}"
PLAYWRIGHT_SECRET="${PLAYWRIGHT_SECRET:-ai-tutor-playwright-live-secret}"
PLAYWRIGHT_FIXTURES_CONFIGMAP="${PLAYWRIGHT_FIXTURES_CONFIGMAP:-ai-tutor-playwright-fixtures}"

echo "Waiting for frontend ${WORKLOAD_TYPE} rollout: ${WORKLOAD_NAME}"
oc rollout status "${WORKLOAD_TYPE}/${WORKLOAD_NAME}" -n "${NAMESPACE}" --timeout="${TIMEOUT}"

echo "Checking live Playwright inputs"
oc get secret "${PLAYWRIGHT_SECRET}" -n "${NAMESPACE}" >/dev/null
oc get configmap "${PLAYWRIGHT_FIXTURES_CONFIGMAP}" -n "${NAMESPACE}" >/dev/null

echo "Starting frontend post-deployment quality check: ${JOB_NAME}"
oc delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found
oc apply -f k8s/quality-checks/job.yaml -n "${NAMESPACE}"

if ! oc wait --for=condition=complete "job/${JOB_NAME}" -n "${NAMESPACE}" --timeout="${TIMEOUT}"; then
  echo "Frontend quality check did not complete successfully. Recent logs:"
  oc logs "job/${JOB_NAME}" -n "${NAMESPACE}" || true
  exit 1
fi

oc logs "job/${JOB_NAME}" -n "${NAMESPACE}"
echo "Frontend post-deployment quality check completed."
