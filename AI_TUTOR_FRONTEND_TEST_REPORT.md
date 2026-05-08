# AI Tutor Frontend Testing and Observability

Last updated: 2026-05-08

This document is the frontend source of truth for AI Tutor testing in `NAGA-open-webui`.

## Scope

Repository:

- `NAGA-open-webui`

Branch:

- `rs/ai-tutor-tests`

Related backend repository:

- `AI_Tutor_Analysis`, branch `feature/test-suite-expansion`

The frontend owns the browser/UI layer and calls the backend analytics services. Backend smoke, integration, health, and external-service checks are documented in the backend repo. Frontend OpenShift checks focus on live browser workflows against the deployed frontend.

## Stage Ownership

GitHub Actions runs:

- AI Tutor Vitest unit/component checks
- mocked Playwright dashboard workflows
- artifacts for frontend results, Playwright reports, videos, and quality metrics
- Grafana Cloud forwarding when Grafana secrets are configured

OpenShift runs:

- live Playwright AI Tutor workflows against the deployed dev frontend
- Pushgateway metric publishing for deployed-environment browser validation

OpenShift does not run:

- Vitest unit/component checks
- mocked Playwright checks
- backend pytest tests

Those already run in GitHub Actions or the backend OpenShift quality BuildConfig. Keeping them out of OpenShift avoids duplicate compute and makes OpenShift failures mean "deployed environment/browser workflow problem."

## Local Checks

Activate the project environment before using Python-backed tooling:

```bash
conda activate oi
```

Focused AI Tutor Vitest checks:

```bash
cd NAGA-open-webui
npm run test:frontend -- --run \
  src/lib/apis/aiTutor/index.test.ts \
  src/lib/utils/__tests__/aiTutorSessionCache.test.ts \
  src/lib/utils/__tests__/aiTutorTesting.test.ts \
  src/lib/stores/__tests__/aiTutorWorkspaceModels.test.ts
```

Mocked Playwright dashboard checks:

```bash
PLAYWRIGHT_BROWSERS_PATH=0 npm run test:e2e:ui -- playwright/tests/ai-tutor-dashboard.mocked.spec.ts
```

Live Playwright checks require real dev accounts, a reachable app, and a homework PDF:

```bash
PLAYWRIGHT_RUN_LIVE=1 \
PLAYWRIGHT_BASE_URL="http://localhost:8080" \
PLAYWRIGHT_ADMIN_EMAIL="<admin-or-instructor-email>" \
PLAYWRIGHT_ADMIN_PASSWORD="<admin-or-instructor-password>" \
PLAYWRIGHT_STUDENT_EMAIL="<student-email>" \
PLAYWRIGHT_STUDENT_PASSWORD="<student-password>" \
PLAYWRIGHT_HOMEWORK_PDF_PATH="$(pwd)/playwright/fixtures/Math_HW.pdf" \
PLAYWRIGHT_BROWSERS_PATH=0 \
npm run test:e2e:ui -- --project=chromium playwright/tests/ai-tutor-dashboard.live.spec.ts
```

## GitHub Actions

Workflow:

- `.github/workflows/ai-tutor-playwright-tests.yml`

Triggers:

- pushes to `rs/ai-tutor-tests` that touch frontend source, Playwright, package files, scripts, or the workflow
- manual `workflow_dispatch`

Default checks:

- installs Node 22 dependencies with `npm ci`
- installs Playwright browsers
- runs focused AI Tutor Vitest checks
- runs mocked Playwright dashboard workflows
- uploads Playwright report and videos
- uploads Vitest JUnit results
- creates a quality metrics artifact
- forwards metrics to Grafana Cloud when secrets are configured

Optional live GitHub mode:

- `workflow_dispatch` input `run_live=true`
- requires live Playwright secrets and a reachable `PLAYWRIGHT_BASE_URL`
- not the default path for OpenShift dev validation

Required Grafana Cloud GitHub secrets:

- `GRAFANA_CLOUD_PROMETHEUS_URL`
- `GRAFANA_CLOUD_PROMETHEUS_USER`
- `GRAFANA_CLOUD_PROMETHEUS_PASSWORD`

Optional live GitHub secrets:

- `PLAYWRIGHT_BASE_URL`
- `PLAYWRIGHT_ADMIN_EMAIL`
- `PLAYWRIGHT_ADMIN_PASSWORD`
- `PLAYWRIGHT_STUDENT_EMAIL`
- `PLAYWRIGHT_STUDENT_PASSWORD`
- `PLAYWRIGHT_HOMEWORK_PDF_PATH`

## OpenShift Dev

Namespace:

- `rit-genai-naga-dev`

Files:

- `k8s/quality-checks/buildconfig.yaml`
- `k8s/quality-checks/job.yaml`
- `k8s/quality-checks/README.md`
- `scripts/run_openshift_frontend_quality_checks_from_build.sh`
- `scripts/run_openshift_frontend_quality_checks.sh`
- `playwright/README.md`

OpenShift objects:

- ImageStream signal: `open-webui:latest`
- ImageStream: `ai-tutor-frontend-quality-checks`
- BuildConfig: `ai-tutor-frontend-quality-checks`
- optional explicit rerun Job: `ai-tutor-frontend-post-deploy-quality-check`

The existing app delivery flow is preserved:

- frontend app images can continue to be pushed to `registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest`
- the Helm-managed `StatefulSet/open-webui` can continue pulling that external image
- the OpenShift `open-webui:latest` ImageStream tracks the external image only as a test automation signal

Automatic test trigger:

```text
external frontend image is pushed
OpenShift imports the new digest into open-webui:latest
ai-tutor-frontend-quality-checks starts from the ImageChange trigger
quality_checks/Dockerfile builds the Playwright quality image from rs/ai-tutor-tests
postCommit runs scripts/run_openshift_frontend_quality_checks_from_build.sh
live Playwright runs against http://open-webui.rit-genai-naga-dev.svc:80
metrics are pushed to ai-tutor-quality-pushgateway
```

The scheduled ImageStream import is automatic, but not guaranteed to run the exact second the external registry push completes. For immediate validation after a manual frontend build:

```bash
oc import-image open-webui:latest \
  --from=registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest \
  --reference-policy=source \
  --confirm \
  -n rit-genai-naga-dev
```

## OpenShift Required Config

Default non-secret env:

- `PLAYWRIGHT_RUN_LIVE=1`
- `PLAYWRIGHT_STRICT_LIVE_CHECKS=1`
- `PLAYWRIGHT_SKIP_WEB_SERVER=1`
- `PLAYWRIGHT_BASE_URL=http://open-webui.rit-genai-naga-dev.svc:80`
- `PLAYWRIGHT_WORKERS=1`
- `PLAYWRIGHT_RETRIES=0`
- `PLAYWRIGHT_VIDEO=off`
- `PLAYWRIGHT_HOMEWORK_PDF_PATH=/workspace/playwright/fixtures/Math_HW.pdf`
- `QUALITY_ENVIRONMENT=openshift-dev`
- `QUALITY_REPOSITORY=NAGA-open-webui`
- `QUALITY_BRANCH=rs/ai-tutor-tests`
- `QUALITY_SOURCE=openshift-frontend-build-triggered-playwright`
- `QUALITY_PUSHGATEWAY_URL=http://ai-tutor-quality-pushgateway:9091`
- `QUALITY_FORWARD_SECONDS=75`

Required OpenShift secret:

- name: `ai-tutor-playwright-live-secret`
- keys:
  - `admin-email`
  - `admin-password`
  - `student-email`
  - `student-password`

BuildConfig secret mount:

- `/var/run/ai-tutor-playwright-live-secret`

Create or update with placeholders:

```bash
oc create secret generic ai-tutor-playwright-live-secret \
  -n rit-genai-naga-dev \
  --from-literal=admin-email='<admin-or-instructor-email>' \
  --from-literal=admin-password='<admin-or-instructor-password>' \
  --from-literal=student-email='<student-email>' \
  --from-literal=student-password='<student-password>' \
  --dry-run=client -o yaml | oc apply -f -
```

Do not put these values in source control or Docker strategy env.

## Homework PDF Fixture

The OpenShift live upload fixture is tracked in Git:

- repo path: `playwright/fixtures/Math_HW.pdf`
- image path: `/workspace/playwright/fixtures/Math_HW.pdf`

To change the PDF used by OpenShift:

1. Replace `playwright/fixtures/Math_HW.pdf` with the new PDF using the same filename.
2. Commit and push the change to `rs/ai-tutor-tests`.
3. Rebuild or trigger the frontend quality BuildConfig so the updated fixture is baked into the image.

The PDF should not be stored in an OpenShift Secret or ConfigMap. Tracking it in Git makes test input changes reviewable and reproducible.

## Live Playwright Workflows

Spec:

- `playwright/tests/ai-tutor-dashboard.live.spec.ts`

Workflow coverage:

- admin/instructor uploads a homework PDF
- student opens chat, selects a model if needed, sends a message, and waits for an assistant response or clear failure
- admin/instructor opens the topic analytics dashboard and verifies key UI elements

OpenShift uses strict mode:

```bash
PLAYWRIGHT_STRICT_LIVE_CHECKS=1
```

Missing live prerequisites fail in OpenShift. Examples:

- unreadable PDF fixture
- missing credentials
- login failure
- missing homework model or upload area
- no usable chat model
- inaccessible dashboard route
- clear error toast during an asserted workflow

## Metrics and Dashboards

Metrics source:

- `scripts/serve_playwright_metrics.py`

Pushgateway:

- `http://ai-tutor-quality-pushgateway:9091`

Pushgateway grouping:

- job: `ai-tutor-quality`
- `environment=openshift-dev`
- `repository=NAGA-open-webui`

Dashboard JSON:

- `observability/grafana/dashboards/ai-tutor-frontend-github-quality.json`

Dashboard expectations:

- GitHub Vitest and mocked Playwright results are separate from OpenShift live Playwright results
- latest-run panels should not stack counts across repeated runs
- failure panels should make it clear whether CI or OpenShift failed
- labels should include source, repository, branch, environment, run id, and commit when available

Telemetry must not include credentials, uploaded file contents, student submissions, database rows, or API response bodies.

## Resources

OpenShift quality image build:

- request: `500m CPU`, `1Gi memory`
- limit: `2 CPU`, `4Gi memory`

Explicit Job runner:

- request: `1 CPU`, `2Gi memory`
- limit: `2 CPU`, `4Gi memory`
- `PLAYWRIGHT_WORKERS=1`
- `PLAYWRIGHT_VIDEO=off`
- `ttlSecondsAfterFinished: 3600`
- `backoffLimit: 0`

These values are intentionally conservative for a single Chromium worker. Increase them only after checking actual OpenShift run usage.

## Operational Commands

Apply/update the OpenShift quality BuildConfig:

```bash
oc apply -f k8s/quality-checks/buildconfig.yaml -n rit-genai-naga-dev
```

Manual quality build:

```bash
oc start-build ai-tutor-frontend-quality-checks --follow --wait -n rit-genai-naga-dev
```

Trigger from external image import:

```bash
oc import-image open-webui:latest \
  --from=registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest \
  --reference-policy=source \
  --confirm \
  -n rit-genai-naga-dev
```

Explicit Job rerun:

```bash
bash scripts/run_post_deploy_frontend_quality_check.sh
```

Check recent frontend quality builds:

```bash
oc get builds -n rit-genai-naga-dev | grep ai-tutor-frontend-quality-checks
```

## Current Limitations

- BuildConfig ImageChange automation is not a strict rollout gate.
- Frontend automation depends on the external image digest being imported into `open-webui:latest`.
- For hard build/deploy/test orchestration, use OpenShift Pipelines/Tekton or ArgoCD post-sync hooks with team-approved RBAC.
- GitHub Actions should not reach VPN-only OpenShift services unless a secure service-account-based route is approved.
