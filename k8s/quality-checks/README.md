# AI Tutor Frontend Post-Deployment Quality Checks on OpenShift

This runs AI Tutor frontend checks after the OpenShift dev frontend StatefulSet is rebuilt and rolled out:

- live Playwright dashboard workflows against the deployed OpenShift frontend
- OpenShift Pushgateway metric publishing

It does not run Vitest or mocked Playwright here. Those already run in GitHub Actions. The OpenShift job is only for post-deployment browser validation of the deployed dev environment.

This frontend flow is build-triggered from the frontend app ImageStream. The backend `AI_Tutor_Analysis` repo has its own BuildConfig image-change trigger for backend smoke, integration, health, and external-service checks; that backend trigger does not run frontend Playwright.

For the full frontend local, GitHub Actions, Grafana Cloud, and OpenShift setup, see:

- `../../AI_TUTOR_FRONTEND_TEST_REPORT.md`

## One-time build setup

```bash
oc apply -f k8s/quality-checks/buildconfig.yaml -n rit-genai-naga-dev
oc start-build ai-tutor-frontend-quality-checks -n rit-genai-naga-dev --follow
```

The quality-check BuildConfig watches:

```text
open-webui:latest
```

When the frontend app build updates the `open-webui:latest` ImageStreamTag, OpenShift starts `ai-tutor-frontend-quality-checks`. The quality build runs `scripts/run_openshift_frontend_quality_checks_from_build.sh` as its `postCommit` hook.

Important: this immediate trigger requires the frontend app build to publish to the `open-webui:latest` ImageStreamTag. If the app build only pushes `registry.cloud.rt.nyu.edu/rit-genai-poc/naga-open-webui:latest` as a raw DockerImage, OpenShift has no ImageStream update to watch and the quality BuildConfig will not start immediately.

## One-Time Live Test Inputs

Create the live Playwright credentials secret from real dev test accounts:

```bash
oc create secret generic ai-tutor-playwright-live-secret \
  -n rit-genai-naga-dev \
  --from-literal=admin-email='<admin-or-instructor-email>' \
  --from-literal=admin-password='<admin-or-instructor-password>' \
  --from-literal=student-email='<student-email>' \
  --from-literal=student-password='<student-password>' \
  --dry-run=client -o yaml | oc apply -f -
```

Create the PDF fixture ConfigMap from a small non-sensitive homework PDF:

```bash
oc create configmap ai-tutor-playwright-fixtures \
  -n rit-genai-naga-dev \
  --from-file=homework.pdf=/path/to/homework.pdf \
  --dry-run=client -o yaml | oc apply -f -
```

## Build, Deploy, and Test

This uses the current user's OpenShift permissions. It starts the frontend quality image build, starts the frontend app build, restarts the frontend StatefulSet so it pulls the new image, waits for rollout, runs the quality Job, sends metrics, and exits.

```bash
bash scripts/run_frontend_build_deploy_quality_check.sh
```

If the frontend was already rebuilt and you only want to run the post-deployment check:

```bash
bash scripts/run_post_deploy_frontend_quality_check.sh
```

This is intentionally not scheduled. It runs only after a deployment rollout or when someone explicitly runs the same commands.

The Job uses resources only while it runs, sends metrics, then exits.

The build-triggered path does not use the Job. It runs inside the quality-check build hook, mounts `ai-tutor-playwright-live-secret` and `ai-tutor-playwright-fixtures` as read-only build volumes, pushes metrics to the namespace Pushgateway, then exits.

## Resource Profile

The job requests `1 CPU` and `2Gi` memory, with a `2 CPU` and `4Gi` limit. That is intentionally scoped to one Chromium worker and no video recording:

```yaml
PLAYWRIGHT_WORKERS: "1"
PLAYWRIGHT_VIDEO: "off"
```

Increase only after checking actual pod usage from a real run.
