#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

QUALITY_FORWARD_SECONDS="${QUALITY_FORWARD_SECONDS:-75}"
QUALITY_PROMETHEUS_CONFIG_PATH="${QUALITY_PROMETHEUS_CONFIG_PATH:-/tmp/naga-open-webui-grafana-cloud-prometheus.yml}"
PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-prom/prometheus:v3.2.1}"

python "${SCRIPT_DIR}/write_grafana_cloud_prometheus_config.py" --output "${QUALITY_PROMETHEUS_CONFIG_PATH}"

if [[ "${QUALITY_FORWARD_DRY_RUN:-0}" == "1" ]]; then
  echo "Generated Prometheus config at ${QUALITY_PROMETHEUS_CONFIG_PATH}"
  echo "Dry run enabled; not starting Prometheus."
  exit 0
fi

docker_args=(run --rm -v "${QUALITY_PROMETHEUS_CONFIG_PATH}:/etc/prometheus/prometheus.yml:ro" "${PROMETHEUS_IMAGE}" --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --web.listen-address=:9090)
if [[ "$(uname -s)" != "Darwin" ]]; then
  docker_args=(run --rm --add-host=host.docker.internal:host-gateway -v "${QUALITY_PROMETHEUS_CONFIG_PATH}:/etc/prometheus/prometheus.yml:ro" "${PROMETHEUS_IMAGE}" --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --web.listen-address=:9090)
fi

docker "${docker_args[@]}" &
prometheus_pid=$!

cleanup() {
  if kill -0 "${prometheus_pid}" >/dev/null 2>&1; then
    kill "${prometheus_pid}" >/dev/null 2>&1 || true
    wait "${prometheus_pid}" >/dev/null 2>&1 || true
  fi
  if [[ "${QUALITY_KEEP_PROMETHEUS_CONFIG:-0}" != "1" ]]; then
    rm -f "${QUALITY_PROMETHEUS_CONFIG_PATH}"
  fi
}
trap cleanup EXIT

echo "Forwarding metrics to Grafana Cloud for ${QUALITY_FORWARD_SECONDS}s..."
sleep "${QUALITY_FORWARD_SECONDS}"
echo "Finished Grafana Cloud forwarding window."
