#!/usr/bin/env bash
set -euo pipefail

mkdir -p quality-results playwright-report test-results

export QUALITY_METRICS_TARGET="${QUALITY_METRICS_TARGET:-127.0.0.1:9109}"
export QUALITY_ENVIRONMENT="${QUALITY_ENVIRONMENT:-openshift-dev}"
export QUALITY_REPOSITORY="${QUALITY_REPOSITORY:-NAGA-open-webui}"
export QUALITY_BRANCH="${QUALITY_BRANCH:-rs/ai-tutor-tests}"
export QUALITY_SOURCE="${QUALITY_SOURCE:-openshift-frontend-checks}"
export QUALITY_FORWARD_SECONDS="${QUALITY_FORWARD_SECONDS:-75}"
export QUALITY_PROMETHEUS_CONFIG_PATH="${QUALITY_PROMETHEUS_CONFIG_PATH:-/tmp/naga-open-webui-grafana-cloud-prometheus.yml}"
export PLAYWRIGHT_VIDEO="${PLAYWRIGHT_VIDEO:-off}"
export PLAYWRIGHT_RUN_LIVE="${PLAYWRIGHT_RUN_LIVE:-0}"
export PLAYWRIGHT_WEB_SERVER_COMMAND="${PLAYWRIGHT_WEB_SERVER_COMMAND:-npx vite dev --host 127.0.0.1 --port 4173}"
export PLAYWRIGHT_WORKERS="${PLAYWRIGHT_WORKERS:-1}"
export PLAYWRIGHT_RETRIES="${PLAYWRIGHT_RETRIES:-0}"

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
npx playwright test playwright/tests/ai-tutor-dashboard.mocked.spec.ts --project=chromium --workers="${PLAYWRIGHT_WORKERS}" --retries="${PLAYWRIGHT_RETRIES}" || playwright_status=$?

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

python3 scripts/write_grafana_cloud_prometheus_config.py --output "${QUALITY_PROMETHEUS_CONFIG_PATH}"

prometheus \
  --config.file="${QUALITY_PROMETHEUS_CONFIG_PATH}" \
  --storage.tsdb.path=/tmp/prometheus \
  --web.listen-address=127.0.0.1:9090 &
prometheus_pid=$!

sleep "${QUALITY_FORWARD_SECONDS}"
kill "${prometheus_pid}" >/dev/null 2>&1 || true
wait "${prometheus_pid}" >/dev/null 2>&1 || true

if [[ "${vitest_status}" != "0" || "${playwright_status}" != "0" ]]; then
  echo "Frontend quality checks completed with failures: vitest=${vitest_status}, playwright=${playwright_status}"
  exit 1
fi

echo "Frontend quality checks completed successfully."
