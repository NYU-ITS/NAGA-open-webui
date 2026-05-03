# AI Tutor Frontend Quality Checks on OpenShift

This runs the non-live AI Tutor frontend checks in OpenShift dev:

- Vitest unit/component checks for AI Tutor frontend code
- Mocked Playwright dashboard workflows
- Grafana Cloud metric forwarding

It does not use test accounts and does not hit live user flows.

## One-time build setup

```bash
oc apply -f k8s/quality-checks/buildconfig.yaml -n rit-genai-naga-dev
oc start-build ai-tutor-frontend-quality-checks -n rit-genai-naga-dev --follow
```

## Manual run

```bash
oc delete job ai-tutor-frontend-quality-check -n rit-genai-naga-dev --ignore-not-found
oc apply -f k8s/quality-checks/job.yaml -n rit-genai-naga-dev
oc logs job/ai-tutor-frontend-quality-check -n rit-genai-naga-dev -f
```

## Hourly run

```bash
oc apply -f k8s/quality-checks/cronjob.yaml -n rit-genai-naga-dev
```

The hourly job starts at minute 20 of each hour, uses resources only while it runs, sends metrics, then exits.
