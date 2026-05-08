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
- OpenShift post-deployment frontend quality checks for live Playwright.
- Grafana dashboard JSON for separate GitHub and OpenShift frontend results.

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
- `k8s/quality-checks/README.md`

OpenShift objects:

- ImageStream signal: `open-webui:latest`
- BuildConfig/ImageStream image: `ai-tutor-frontend-quality-checks`
- post-deployment Job: `ai-tutor-frontend-post-deploy-quality-check`

Automatic trigger:

- `open-webui:latest` tracks the existing external image `registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest`
- when OpenShift imports a new external image digest into that ImageStream tag, it triggers `ai-tutor-frontend-quality-checks`
- the frontend quality build runs `scripts/run_openshift_frontend_quality_checks_from_build.sh` as its `postCommit` hook
- the hook mounts `ai-tutor-playwright-live-secret` and `ai-tutor-playwright-fixtures` as read-only build volumes
- this does not change the current app BuildConfig external registry output or the Helm-managed `open-webui` StatefulSet image

What OpenShift runs today:

- live Playwright AI Tutor dashboard workflows against the deployed frontend

What OpenShift does not run:

- Vitest unit/component checks
- mocked Playwright dashboard workflows

Reason:

- those checks already run in GitHub Actions and do not need to be repeated in OpenShift

## Grafana

Dashboard JSON:

- `observability/grafana/dashboards/ai-tutor-frontend-github-quality.json`

The dashboard separates:

- GitHub Vitest checks
- GitHub Playwright checks
- OpenShift live Playwright post-deployment checks

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

Current OpenShift live Playwright checks:

- request: `1 CPU`, `2Gi memory`
- limit: `2 CPU`, `4Gi memory`
- workers: `1`
- video: `off`

## Current Limitations

- Live Playwright checks require real dev test accounts and a small homework PDF fixture.
- GitHub Actions should not access VPN-only OpenShift services unless a secure service-account-based path is approved.
