# AI Tutor Frontend Post-Deployment Quality Checks on OpenShift

This README documents the frontend OpenShift quality-check implementation for `NAGA-open-webui`.

For the full frontend testing, GitHub Actions, Grafana, and OpenShift overview, see:

- `../../AI_TUTOR_FRONTEND_TEST_REPORT.md`
- `../../playwright/README.md`

## Purpose

These checks answer one deployed-environment question:

```text
After the frontend dev image changes, can the deployed OpenShift frontend still complete the AI Tutor browser workflows?
```

They do not run Vitest or mocked Playwright. Those already run in GitHub Actions. OpenShift runs only live browser validation against the deployed dev frontend.

## OpenShift Objects

Applied from `k8s/quality-checks/buildconfig.yaml`:

- ImageStream signal: `open-webui:latest`
- ImageStream: `ai-tutor-frontend-quality-checks`
- BuildConfig: `ai-tutor-frontend-quality-checks`

Optional explicit rerun object from `k8s/quality-checks/job.yaml`:

- Job: `ai-tutor-frontend-post-deploy-quality-check`

Namespace:

- `rit-genai-naga-dev`

## External Registry Flow Is Preserved

The existing frontend app delivery path is not replaced:

- the frontend app BuildConfig can still push to `registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest`
- the Helm-managed `StatefulSet/open-webui` can still pull the external registry image
- the `open-webui:latest` ImageStream is only an OpenShift-native signal for test automation

The ImageStream tracks:

```text
registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest
```

with `referencePolicy: Source`, so the existing external image reference remains the source of truth.

## Automatic Trigger Flow

The quality BuildConfig watches:

```text
open-webui:latest
```

Expected flow:

```text
frontend app image is pushed to the external registry
OpenShift imports the new external digest into open-webui:latest
ai-tutor-frontend-quality-checks build starts automatically
quality_checks/Dockerfile builds the Playwright quality-check image
postCommit runs scripts/run_openshift_frontend_quality_checks_from_build.sh
live Playwright runs against http://open-webui.rit-genai-naga-dev.svc:80
metrics are pushed to ai-tutor-quality-pushgateway
Playwright reports/results are uploaded to ObjectBucket/S3 when bucket credentials are available
build succeeds or fails with the Playwright result
```

OpenShift scheduled image import is automatic, but it may not happen immediately after an external registry push. For an immediate run after a manual frontend build, import the image explicitly:

```bash
oc import-image open-webui:latest \
  --from=registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest \
  --reference-policy=source \
  --confirm \
  -n rit-genai-naga-dev
```

For a strict "build, rollout, then test" gate, move this into OpenShift Pipelines/Tekton or an ArgoCD post-sync hook with service-account RBAC approved by the platform team.

## Test Selection

The OpenShift runner executes:

```bash
npx playwright test playwright/tests/ai-tutor-dashboard.live.spec.ts \
  --project=chromium \
  --workers="${PLAYWRIGHT_WORKERS}" \
  --retries="${PLAYWRIGHT_RETRIES}"
```

OpenShift runs:

- live admin/instructor homework upload workflow
- live student chat workflow
- live admin/instructor analytics dashboard workflow

OpenShift does not run:

- Vitest unit/component checks
- mocked Playwright UI checks
- backend pytest checks

## Required Config

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
- `QUALITY_UPLOAD_ARTIFACTS=1`
- `ARTIFACT_PREFIX=openshift/frontend/dev`

Required secret:

- name: `ai-tutor-playwright-live-secret`
- keys:
  - `admin-email`
  - `admin-password`
  - `student-email`
  - `student-password`

The BuildConfig mounts this secret read-only at:

```text
/var/run/ai-tutor-playwright-live-secret
```

Create/update the secret with placeholders:

```bash
oc create secret generic ai-tutor-playwright-live-secret \
  -n rit-genai-naga-dev \
  --from-literal=admin-email='<admin-or-instructor-email>' \
  --from-literal=admin-password='<admin-or-instructor-password>' \
  --from-literal=student-email='<student-email>' \
  --from-literal=student-password='<student-password>' \
  --dry-run=client -o yaml | oc apply -f -
```

Do not put Playwright credentials in source control, ConfigMaps, Docker strategy env, or backend secrets.

## Homework PDF Fixture

The live upload fixture is tracked in Git:

```text
playwright/fixtures/Math_HW.pdf
```

Inside the quality image it is read from:

```text
/workspace/playwright/fixtures/Math_HW.pdf
```

To change the OpenShift test input, replace `playwright/fixtures/Math_HW.pdf` with a new file using the same name, commit it, push it, and rebuild the quality-check image. This keeps the fixture reviewable and versioned.

The fixture should not be stored in the Playwright secret. Secrets are for credentials only.

## Strict Failure Behavior

OpenShift sets:

```bash
PLAYWRIGHT_STRICT_LIVE_CHECKS=1
```

Missing prerequisites fail the quality signal. Examples:

- missing secret key
- unreadable PDF fixture
- login failure
- missing homework upload area or homework model
- no usable chat model for the student flow
- route or dashboard inaccessible
- workflow error toast during an asserted action

This prevents a green OpenShift signal when the environment is incomplete.

## Apply or Update

```bash
oc apply -f k8s/quality-checks/buildconfig.yaml -n rit-genai-naga-dev
```

Check the trigger:

```bash
oc get buildconfig ai-tutor-frontend-quality-checks \
  -n rit-genai-naga-dev \
  -o jsonpath='{.spec.triggers}'
```

## Manual Reruns

Run the quality BuildConfig manually:

```bash
oc start-build ai-tutor-frontend-quality-checks --follow --wait -n rit-genai-naga-dev
```

Run the explicit Job path:

```bash
bash scripts/run_post_deploy_frontend_quality_check.sh
```

The Job path uses the latest `ai-tutor-frontend-quality-checks:latest` image, injects credentials through `secretKeyRef`, runs live Playwright, publishes metrics, and exits.

## Metrics

The runner starts `scripts/serve_playwright_metrics.py`, scrapes local metrics, and pushes them to:

```text
http://ai-tutor-quality-pushgateway:9091
```

Pushgateway grouping:

- job: `ai-tutor-quality`
- `environment=openshift-dev`
- `repository=NAGA-open-webui`

Dashboard JSON:

- `observability/grafana/dashboards/ai-tutor-frontend-github-quality.json`

Metrics must remain telemetry only. Do not export credentials, uploaded file contents, student submissions, request bodies, or database rows.

## Artifact Upload

After metrics are scraped locally, the runner uploads heavy Playwright artifacts when ObjectBucket/S3 credentials are available:

- `playwright-report/`
- `test-results/`
- screenshots, videos, traces, and raw Playwright files inside those directories

The upload path is:

```text
openshift/frontend/dev/runs/<run-id>/
```

The uploader also writes:

```text
openshift/frontend/dev/latest.json
openshift/frontend/dev/index.json
```

Artifact upload is best-effort. If the bucket secret/config is missing, the runner logs a clear skip and the quality result still comes from Playwright plus the pushed metrics.

## Resources

Quality build:

- request: `500m CPU`, `1Gi memory`
- limit: `2 CPU`, `4Gi memory`

Explicit Job:

- request: `1 CPU`, `2Gi memory`
- limit: `2 CPU`, `4Gi memory`
- `PLAYWRIGHT_WORKERS=1`
- `PLAYWRIGHT_VIDEO=off`
- `ttlSecondsAfterFinished: 3600`
- `backoffLimit: 0`

Build history is capped:

- `successfulBuildsHistoryLimit: 2`
- `failedBuildsHistoryLimit: 2`

This keeps test automation short-lived and avoids wasting namespace resources.

## Troubleshooting

Check builds:

```bash
oc get builds -n rit-genai-naga-dev | grep ai-tutor-frontend-quality-checks
```

Follow a build:

```bash
oc logs -f build/ai-tutor-frontend-quality-checks-<number> -n rit-genai-naga-dev
```

Check the external image import:

```bash
oc get istag open-webui:latest -n rit-genai-naga-dev
```

Check quality pods:

```bash
oc get pods -n rit-genai-naga-dev | grep quality
```

Common failures:

- `Missing mounted Playwright secret file`: update `ai-tutor-playwright-live-secret`
- `Missing Playwright homework fixture`: verify `playwright/fixtures/Math_HW.pdf` exists in the pushed branch and image
- login failure: verify dev test accounts and passwords
- missing homework model/upload area: configure the instructor account/group/workspace model
- no chat model: configure a model visible to the student account
- no metrics in Grafana: verify Pushgateway and dashboard source labels
