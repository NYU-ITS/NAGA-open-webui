#!/usr/bin/env bash
set -euo pipefail

SECRET_MOUNT_PATH="${PLAYWRIGHT_SECRET_MOUNT_PATH:-/var/run/ai-tutor-playwright-live-secret}"
FIXTURE_MOUNT_PATH="${PLAYWRIGHT_FIXTURE_MOUNT_PATH:-/workspace/playwright/fixtures}"

export QUALITY_ENVIRONMENT="${QUALITY_ENVIRONMENT:-openshift-dev}"
export QUALITY_REPOSITORY="${QUALITY_REPOSITORY:-NAGA-open-webui}"
export QUALITY_BRANCH="${QUALITY_BRANCH:-rs/ai-tutor-tests}"
export QUALITY_SOURCE="${QUALITY_SOURCE:-openshift-frontend-build-triggered-playwright}"
export QUALITY_COMMIT_SHA="${OPENSHIFT_BUILD_COMMIT:-${QUALITY_COMMIT_SHA:-openshift-build}}"
export QUALITY_RUN_ID="${OPENSHIFT_BUILD_NAME:-${HOSTNAME:-openshift-build}}"
export QUALITY_FORWARD_SECONDS="${QUALITY_FORWARD_SECONDS:-75}"
export QUALITY_PUSHGATEWAY_URL="${QUALITY_PUSHGATEWAY_URL:-http://ai-tutor-quality-pushgateway:9091}"
export PLAYWRIGHT_VIDEO="${PLAYWRIGHT_VIDEO:-on}"
export PLAYWRIGHT_RUN_LIVE="${PLAYWRIGHT_RUN_LIVE:-1}"
export PLAYWRIGHT_STRICT_LIVE_CHECKS="${PLAYWRIGHT_STRICT_LIVE_CHECKS:-1}"
export PLAYWRIGHT_SKIP_WEB_SERVER="${PLAYWRIGHT_SKIP_WEB_SERVER:-1}"
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://open-webui.rit-genai-naga-dev.svc:80}"
export PLAYWRIGHT_WORKERS="${PLAYWRIGHT_WORKERS:-1}"
export PLAYWRIGHT_RETRIES="${PLAYWRIGHT_RETRIES:-0}"
export PLAYWRIGHT_TIMEOUT="${PLAYWRIGHT_TIMEOUT:-60000}"
export PLAYWRIGHT_HOMEWORK_PDF_PATH="${PLAYWRIGHT_HOMEWORK_PDF_PATH:-${FIXTURE_MOUNT_PATH}/Math_HW.pdf}"

load_playwright_secret() {
  local missing=0

  for key in admin-email admin-password student-email student-password; do
    if [[ ! -r "${SECRET_MOUNT_PATH}/${key}" ]]; then
      echo "Missing mounted Playwright secret file: ${SECRET_MOUNT_PATH}/${key}" >&2
      missing=1
    fi
  done

  if [[ "${missing}" -ne 0 ]]; then
    return 1
  fi

  export PLAYWRIGHT_ADMIN_EMAIL
  export PLAYWRIGHT_ADMIN_PASSWORD
  export PLAYWRIGHT_STUDENT_EMAIL
  export PLAYWRIGHT_STUDENT_PASSWORD
  PLAYWRIGHT_ADMIN_EMAIL="$(<"${SECRET_MOUNT_PATH}/admin-email")"
  PLAYWRIGHT_ADMIN_PASSWORD="$(<"${SECRET_MOUNT_PATH}/admin-password")"
  PLAYWRIGHT_STUDENT_EMAIL="$(<"${SECRET_MOUNT_PATH}/student-email")"
  PLAYWRIGHT_STUDENT_PASSWORD="$(<"${SECRET_MOUNT_PATH}/student-password")"
}

if [[ ! -r "${PLAYWRIGHT_HOMEWORK_PDF_PATH}" ]]; then
  echo "Missing Playwright homework fixture: ${PLAYWRIGHT_HOMEWORK_PDF_PATH}" >&2
  exit 1
fi

load_playwright_secret

exec bash scripts/run_openshift_frontend_quality_checks.sh
