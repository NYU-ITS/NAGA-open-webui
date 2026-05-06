# AI Tutor Frontend Scheduled Quality Checks on OpenShift

This runs scheduled AI Tutor frontend checks in OpenShift dev:

- Vitest unit/component checks for AI Tutor frontend code
- Mocked Playwright dashboard workflows are supported but disabled by default
  in OpenShift dev because Chromium + Vite can exceed the small dev memory limit.
- Grafana Cloud metric forwarding

It does not use test accounts and does not hit live user flows.

For the full frontend local, GitHub Actions, Grafana Cloud, and OpenShift setup, see:

- `../../AI_TUTOR_FRONTEND_TEST_REPORT.md`

## One-time build setup

```bash
oc apply -f k8s/quality-checks/buildconfig.yaml -n rit-genai-naga-dev
oc start-build ai-tutor-frontend-quality-checks -n rit-genai-naga-dev --follow
```

## Manual Run

```bash
oc delete job ai-tutor-frontend-scheduled-quality-check -n rit-genai-naga-dev --ignore-not-found
oc apply -f k8s/quality-checks/job.yaml -n rit-genai-naga-dev
oc logs job/ai-tutor-frontend-scheduled-quality-check -n rit-genai-naga-dev -f
```

## Daily Schedule

```bash
oc apply -f k8s/quality-checks/cronjob.yaml -n rit-genai-naga-dev
```

The scheduled job runs daily at 1:00 AM New York time, uses resources only while it runs, sends metrics, then exits.

## Post-Deploy Run

To run the same checks immediately after a dev rollout:

```bash
oc create job ai-tutor-frontend-post-deploy-check-$(date +%s) \
  --from=cronjob/ai-tutor-frontend-scheduled-quality-checks \
  -n rit-genai-naga-dev
```

## Optional mocked Playwright

The Job defaults to Vitest-only in OpenShift dev:

```yaml
RUN_MOCKED_PLAYWRIGHT: "0"
```

Set it to `"1"` only on a larger runner/pod memory limit.
