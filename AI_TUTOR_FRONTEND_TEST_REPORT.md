# AI Tutor Frontend Testing and Observability

Last updated: 2026-05-05

This document describes the current AI Tutor frontend testing setup in `NAGA-open-webui`.

## Current Scope

Branch:

- `rs/ai-tutor-tests`

The frontend calls backend analytics services from `AI_Tutor_Analysis`, but this repository owns the browser/UI layer and frontend unit/component checks.

## What Is Currently Supported

- Vitest checks for AI Tutor frontend API helpers, stores, utilities, and cache behavior.
- Mocked Playwright checks for AI Tutor dashboard UI workflows.
- Optional live Playwright workflow scaffolding.
- GitHub Actions reporting for Vitest and mocked Playwright.
- Grafana Cloud metric forwarding from GitHub Actions.
- OpenShift scheduled frontend quality checks for Vitest.
- Grafana dashboard JSON for frontend GitHub and OpenShift scheduled results.

## Local Checks

Run focused AI Tutor Vitest checks:

```bash
conda activate oi
cd NAGA-open-webui
npm run test:frontend -- --run \
  src/lib/apis/aiTutor/index.test.ts \
  src/lib/utils/__tests__/aiTutorSessionCache.test.ts \
  src/lib/utils/__tests__/aiTutorTesting.test.ts \
  src/lib/stores/__tests__/aiTutorWorkspaceModels.test.ts
```

Run mocked Playwright checks:

```bash
conda activate oi
cd NAGA-open-webui
PLAYWRIGHT_BROWSERS_PATH=0 npm run test:e2e:ui -- playwright/tests/ai-tutor-dashboard.mocked.spec.ts
```

Run the full Playwright AI Tutor suite:

```bash
conda activate oi
cd NAGA-open-webui
PLAYWRIGHT_BROWSERS_PATH=0 npm run test:e2e:ui
```

Live Playwright tests are skipped unless explicitly enabled with environment variables.

## GitHub Actions

Workflow:

- `.github/workflows/ai-tutor-playwright-tests.yml`

What it runs:

- AI Tutor Vitest unit/component checks
- mocked Playwright dashboard workflows
- optional live Playwright workflows when enabled
- Playwright report artifacts
- Playwright video artifacts when available
- Grafana Cloud metrics forwarding

Required Grafana Cloud GitHub secrets:

- `GRAFANA_CLOUD_PROMETHEUS_URL`
- `GRAFANA_CLOUD_PROMETHEUS_USER`
- `GRAFANA_CLOUD_PROMETHEUS_PASSWORD`

Live Playwright workflows require additional environment variables and are not enabled by default.

## OpenShift Dev

Namespace:

- `rit-genai-naga-dev`

Files:

- `k8s/quality-checks/buildconfig.yaml`
- `k8s/quality-checks/job.yaml`
- `k8s/quality-checks/cronjob.yaml`
- `k8s/quality-checks/README.md`

OpenShift objects:

- BuildConfig/ImageStream image: `ai-tutor-frontend-quality-checks`
- manual Job: `ai-tutor-frontend-scheduled-quality-check`
- scheduled CronJob: `ai-tutor-frontend-scheduled-quality-checks`

Schedule:

- daily at `1:00 AM America/New_York`

What OpenShift runs today:

- Vitest-only AI Tutor frontend checks

What OpenShift does not run today:

- Playwright browser workflows

Reason:

- Chromium + Vite exceeded the current small OpenShift dev memory budget during testing. GitHub Actions remains the current place for mocked Playwright checks.

## Grafana

Dashboard JSON:

- `observability/grafana/dashboards/ai-tutor-frontend-github-quality.json`

The dashboard separates:

- GitHub Vitest checks
- GitHub Playwright checks
- OpenShift scheduled frontend checks

The dashboard uses latest-run style queries for stat panels so counts do not stack across repeated runs in the selected time window.

## Live Playwright Requirements

To run live Playwright workflow bots, set:

```bash
export PLAYWRIGHT_RUN_LIVE=1
export PLAYWRIGHT_BASE_URL="http://localhost:8080"
export PLAYWRIGHT_ADMIN_EMAIL="<admin-or-instructor-email>"
export PLAYWRIGHT_ADMIN_PASSWORD="<password>"
export PLAYWRIGHT_STUDENT_EMAIL="<student-email>"
export PLAYWRIGHT_STUDENT_PASSWORD="<password>"
export PLAYWRIGHT_HOMEWORK_PDF_PATH="/absolute/path/to/homework.pdf"
```

Then run:

```bash
conda activate oi
PLAYWRIGHT_BROWSERS_PATH=0 npm run test:e2e:ui -- --project=chromium playwright/tests/ai-tutor-dashboard.live.spec.ts
```

## Resource Guidance

Current OpenShift Vitest checks:

- request: `250m CPU`, `768Mi memory`
- limit: `1 CPU`, `2Gi memory`

Recommended OpenShift Playwright budget:

- minimum request: `1 CPU`, `2Gi memory`
- recommended limit: `2 CPU`, `4Gi memory`
- safer for video/report-heavy runs: `2 CPU`, `6Gi memory`

## Current Limitations

- OpenShift frontend scheduled checks are Vitest-only.
- Live Playwright checks require real accounts and are not enabled by default.
- GitHub Actions should not access VPN-only OpenShift services unless a secure service-account-based path is approved.
