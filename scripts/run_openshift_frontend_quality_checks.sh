#!/usr/bin/env bash
set -euo pipefail

mkdir -p quality-results playwright-report test-results

export QUALITY_METRICS_TARGET="${QUALITY_METRICS_TARGET:-127.0.0.1:9109}"
export QUALITY_ENVIRONMENT="${QUALITY_ENVIRONMENT:-openshift-dev}"
export QUALITY_REPOSITORY="${QUALITY_REPOSITORY:-NAGA-open-webui}"
export QUALITY_BRANCH="${QUALITY_BRANCH:-rs/ai-tutor-tests}"
export QUALITY_SOURCE="${QUALITY_SOURCE:-openshift-frontend-scheduled-checks}"
export QUALITY_FORWARD_SECONDS="${QUALITY_FORWARD_SECONDS:-75}"
export QUALITY_PROMETHEUS_CONFIG_PATH="${QUALITY_PROMETHEUS_CONFIG_PATH:-/tmp/naga-open-webui-grafana-cloud-prometheus.yml}"
export QUALITY_PUSHGATEWAY_URL="${QUALITY_PUSHGATEWAY_URL:-}"
export PLAYWRIGHT_VIDEO="${PLAYWRIGHT_VIDEO:-off}"
export PLAYWRIGHT_RUN_LIVE="${PLAYWRIGHT_RUN_LIVE:-0}"
export PLAYWRIGHT_WEB_SERVER_COMMAND="${PLAYWRIGHT_WEB_SERVER_COMMAND:-npx vite dev --host 127.0.0.1 --port 4173}"
export PLAYWRIGHT_WORKERS="${PLAYWRIGHT_WORKERS:-1}"
export PLAYWRIGHT_RETRIES="${PLAYWRIGHT_RETRIES:-0}"
export RUN_MOCKED_PLAYWRIGHT="${RUN_MOCKED_PLAYWRIGHT:-0}"

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

push_metrics_to_gateway() {
  if [[ -z "${QUALITY_PUSHGATEWAY_URL}" ]]; then
    return 0
  fi

  local metrics_file="/tmp/ai-tutor-frontend-quality-metrics.prom"
  curl -fsS "http://${QUALITY_METRICS_TARGET}/metrics" -o "${metrics_file}"

  local push_url="${QUALITY_PUSHGATEWAY_URL%/}/metrics/job/ai-tutor-quality"
  push_url="${push_url}/environment/$(urlencode "${QUALITY_ENVIRONMENT}")"
  push_url="${push_url}/repository/$(urlencode "${QUALITY_REPOSITORY}")"

  curl -fsS --data-binary @"${metrics_file}" "${push_url}"
  echo "Published AI Tutor frontend quality metrics to Pushgateway."
}

forward_metrics_to_grafana_cloud() {
  if [[ -z "${GRAFANA_CLOUD_PROMETHEUS_URL:-}" || -z "${GRAFANA_CLOUD_PROMETHEUS_USER:-}" || -z "${GRAFANA_CLOUD_PROMETHEUS_PASSWORD:-}" ]]; then
    echo "Grafana Cloud variables are not set; skipping Grafana Cloud forwarding."
    return 0
  fi

  python3 scripts/write_grafana_cloud_prometheus_config.py --output "${QUALITY_PROMETHEUS_CONFIG_PATH}"

  prometheus \
    --config.file="${QUALITY_PROMETHEUS_CONFIG_PATH}" \
    --storage.tsdb.path=/tmp/prometheus \
    --web.listen-address=127.0.0.1:9090 &
  prometheus_pid=$!

  sleep "${QUALITY_FORWARD_SECONDS}"
  kill "${prometheus_pid}" >/dev/null 2>&1 || true
  wait "${prometheus_pid}" >/dev/null 2>&1 || true
}

vitest_status=0
npm run test:frontend -- --run \
  src/lib/utils/__tests__/aiTutorTesting.test.ts \
  src/lib/apis/aiTutor/index.test.ts \
  src/lib/stores/__tests__/aiTutorWorkspaceModels.test.ts \
  src/lib/utils/__tests__/aiTutorSessionCache.test.ts \
  --reporter=default \
  --reporter=junit \
  --outputFile=quality-results/vitest-results.xml || vitest_status=$?

playwright_status=0
if [[ "${RUN_MOCKED_PLAYWRIGHT}" == "1" ]]; then
  npx playwright test playwright/tests/ai-tutor-dashboard.mocked.spec.ts --project=chromium --workers="${PLAYWRIGHT_WORKERS}" --retries="${PLAYWRIGHT_RETRIES}" || playwright_status=$?
else
  echo "Skipping mocked Playwright in OpenShift. Set RUN_MOCKED_PLAYWRIGHT=1 to enable it for a larger runner."
  rm -rf playwright-report
  mkdir -p playwright-report
fi

python3 scripts/serve_playwright_metrics.py \
  --vitest-results quality-results/vitest-results.xml \
  --report playwright-report/index.html \
  --host 127.0.0.1 \
  --port 9109 &
exporter_pid=$!

cleanup() {
  kill "${exporter_pid}" >/dev/null 2>&1 || true
  rm -f "${QUALITY_PROMETHEUS_CONFIG_PATH}"
}
trap cleanup EXIT

sleep 3
curl -fsS "http://${QUALITY_METRICS_TARGET}/metrics" >/dev/null

push_metrics_to_gateway
forward_metrics_to_grafana_cloud

if [[ "${vitest_status}" != "0" || "${playwright_status}" != "0" ]]; then
  echo "Frontend quality checks completed with failures: vitest=${vitest_status}, playwright=${playwright_status}"
  exit 1
fi

echo "Frontend quality checks completed successfully."
