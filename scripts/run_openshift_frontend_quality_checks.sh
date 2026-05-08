#!/usr/bin/env bash
set -euo pipefail

mkdir -p playwright-report test-results

export QUALITY_METRICS_TARGET="${QUALITY_METRICS_TARGET:-127.0.0.1:9109}"
export QUALITY_ENVIRONMENT="${QUALITY_ENVIRONMENT:-openshift-dev}"
export QUALITY_REPOSITORY="${QUALITY_REPOSITORY:-NAGA-open-webui}"
export QUALITY_BRANCH="${QUALITY_BRANCH:-rs/ai-tutor-tests}"
export QUALITY_SOURCE="${QUALITY_SOURCE:-openshift-frontend-live-playwright}"
export QUALITY_FORWARD_SECONDS="${QUALITY_FORWARD_SECONDS:-75}"
export QUALITY_PROMETHEUS_CONFIG_PATH="${QUALITY_PROMETHEUS_CONFIG_PATH:-/tmp/naga-open-webui-grafana-cloud-prometheus.yml}"
export QUALITY_PUSHGATEWAY_URL="${QUALITY_PUSHGATEWAY_URL:-}"
export PLAYWRIGHT_VIDEO="${PLAYWRIGHT_VIDEO:-off}"
export PLAYWRIGHT_RUN_LIVE="${PLAYWRIGHT_RUN_LIVE:-1}"
export PLAYWRIGHT_STRICT_LIVE_CHECKS="${PLAYWRIGHT_STRICT_LIVE_CHECKS:-1}"
export PLAYWRIGHT_SKIP_WEB_SERVER="${PLAYWRIGHT_SKIP_WEB_SERVER:-1}"
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://open-webui.rit-genai-naga-dev.svc:80}"
export PLAYWRIGHT_WORKERS="${PLAYWRIGHT_WORKERS:-1}"
export PLAYWRIGHT_RETRIES="${PLAYWRIGHT_RETRIES:-0}"

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

upload_playwright_artifacts() {
  if [[ "${QUALITY_UPLOAD_ARTIFACTS:-1}" != "1" ]]; then
    echo "OpenShift Playwright artifact upload is disabled."
    return 0
  fi

  python3 scripts/upload_openshift_playwright_artifacts.py \
    --report-dir playwright-report \
    --results-dir test-results \
    --metrics-file /tmp/ai-tutor-frontend-quality-metrics.prom || true
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

playwright_status=0
npx playwright test playwright/tests/ai-tutor-dashboard.live.spec.ts \
  --project=chromium \
  --workers="${PLAYWRIGHT_WORKERS}" \
  --retries="${PLAYWRIGHT_RETRIES}" || playwright_status=$?

python3 scripts/serve_playwright_metrics.py \
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
upload_playwright_artifacts
forward_metrics_to_grafana_cloud

if [[ "${playwright_status}" != "0" ]]; then
  echo "Frontend live Playwright checks completed with failures: playwright=${playwright_status}"
  exit 1
fi

echo "Frontend live Playwright checks completed successfully."
