# Playwright E2E for AI Tutor

This repo uses Playwright for browser-level AI Tutor testing.

For the full frontend testing and observability overview, see:

- `../AI_TUTOR_FRONTEND_TEST_REPORT.md`
- `../k8s/quality-checks/README.md`

## Test Types

Mocked UI tests:

- file: `playwright/tests/ai-tutor-dashboard.mocked.spec.ts`
- run in GitHub Actions
- do not require a real backend, real accounts, or OpenShift
- validate frontend dashboard rendering and UI behavior with mocked API responses

Live workflow tests:

- file: `playwright/tests/ai-tutor-dashboard.live.spec.ts`
- run in OpenShift after frontend image updates
- can also run locally against a reachable app
- require real dev accounts, a usable deployed app, available models, and a readable homework PDF fixture

OpenShift runs only the live workflow tests. Vitest and mocked Playwright remain in GitHub Actions.

## First-Time Setup

Install Playwright browsers:

```bash
npx playwright install
```

If the repo tooling uses Python, activate the shared environment first:

```bash
conda activate oi
```

## Mocked UI Tests

Run without backend dependencies:

```bash
npm run test:e2e:ui -- playwright/tests/ai-tutor-dashboard.mocked.spec.ts
```

These are the browser checks GitHub Actions runs by default.

## Live Workflow Prerequisites

The live tests are real browser automation. The target app must be usable by a human first.

Required:

- `PLAYWRIGHT_RUN_LIVE=1`
- `PLAYWRIGHT_BASE_URL` pointing at the target OpenWebUI app
- admin/instructor email and password
- student email and password
- readable homework PDF
- AI Tutor group visible to the admin/instructor
- homework workspace model available for the selected group
- chat model visible to the student
- backend analytics services reachable from the frontend

OpenShift strict mode:

```bash
PLAYWRIGHT_STRICT_LIVE_CHECKS=1
```

In strict mode, missing prerequisites fail the test run instead of becoming quiet skips.

## Live Environment Variables

Required for local live runs:

- `PLAYWRIGHT_RUN_LIVE=1`
- `PLAYWRIGHT_BASE_URL`
- `PLAYWRIGHT_ADMIN_EMAIL`
- `PLAYWRIGHT_ADMIN_PASSWORD`
- `PLAYWRIGHT_STUDENT_EMAIL`
- `PLAYWRIGHT_STUDENT_PASSWORD`
- `PLAYWRIGHT_HOMEWORK_PDF_PATH`

OpenShift also sets:

- `PLAYWRIGHT_SKIP_WEB_SERVER=1`
- `PLAYWRIGHT_STRICT_LIVE_CHECKS=1`
- `PLAYWRIGHT_WORKERS=1`
- `PLAYWRIGHT_RETRIES=0`
- `PLAYWRIGHT_VIDEO=off`

## Homework PDF Fixture

The OpenShift fixture is tracked in Git:

```text
playwright/fixtures/Math_HW.pdf
```

Inside the OpenShift quality image it is read from:

```text
/workspace/playwright/fixtures/Math_HW.pdf
```

To change the fixture used by OpenShift, replace `playwright/fixtures/Math_HW.pdf` with a new PDF using the same filename, commit it, push it, and rebuild the frontend quality-check image. Do not store the PDF in an OpenShift Secret. Secrets are reserved for credentials.

For local live runs, point `PLAYWRIGHT_HOMEWORK_PDF_PATH` at any readable PDF. If macOS blocks a protected path such as `~/Downloads`, move the file into the repo or another readable directory.

## Live Workflow Details

### Workflow 1: Admin Uploads Homework PDF

Goal: verify an admin/instructor can reach Instructor Setup and upload a homework PDF.

Steps:

1. Sign in through `/api/v1/auths/signin` and inject the token into `localStorage`.
2. Open `/aitutordashboard/instructorsetup`.
3. Close the "What's New" modal if it appears.
4. Expand the "Homework & Answer Files" section when needed.
5. Clear old visible toasts from page load.
6. Set the configured PDF on the hidden homework upload input.
7. Wait for a real success toast or fail on a clear upload error.

### Workflow 2: Student Sends Chat Message

Goal: verify a student can send a chat message and see the assistant response path start.

Steps:

1. Sign in through `/api/v1/auths/signin` and inject the token into `localStorage`.
2. Open `/`.
3. Close the "What's New" modal if it appears.
4. Select the first available model if the UI asks for one.
5. Type a message into `#chat-input`.
6. Submit the message.
7. Wait for an assistant response or a clear error signal.

### Workflow 3: Admin Opens Analytics Dashboard

Goal: verify an admin/instructor can reach AI Tutor analytics.

Steps:

1. Sign in through `/api/v1/auths/signin` and inject the token into `localStorage`.
2. Open `/aitutordashboard/topicanalysis`.
3. Close the "What's New" modal if it appears.
4. Assert that "Topic Analysis by Homework" and "Practice Question" render.

## Run Live Locally

```bash
export PLAYWRIGHT_RUN_LIVE=1
export PLAYWRIGHT_BASE_URL="http://localhost:8080"
export PLAYWRIGHT_ADMIN_EMAIL="<admin-or-instructor-email>"
export PLAYWRIGHT_ADMIN_PASSWORD="<admin-or-instructor-password>"
export PLAYWRIGHT_STUDENT_EMAIL="<student-email>"
export PLAYWRIGHT_STUDENT_PASSWORD="<student-password>"
export PLAYWRIGHT_HOMEWORK_PDF_PATH="$(pwd)/playwright/fixtures/Math_HW.pdf"
export PLAYWRIGHT_BROWSERS_PATH=0

npm run test:e2e:ui -- --project=chromium playwright/tests/ai-tutor-dashboard.live.spec.ts
```

Useful modes:

- headed: `npm run test:e2e:ui:headed -- playwright/tests/ai-tutor-dashboard.live.spec.ts`
- debug: `npm run test:e2e:ui:debug -- playwright/tests/ai-tutor-dashboard.live.spec.ts`

## OpenShift Live Run

OpenShift sets the required env vars and runs:

```bash
npx playwright test playwright/tests/ai-tutor-dashboard.live.spec.ts \
  --project=chromium \
  --workers=1 \
  --retries=0
```

The OpenShift BuildConfig path:

```text
open-webui:latest ImageStreamTag updates
-> ai-tutor-frontend-quality-checks BuildConfig starts
-> postCommit loads ai-tutor-playwright-live-secret
-> postCommit verifies /workspace/playwright/fixtures/Math_HW.pdf
-> live Playwright runs against http://open-webui.rit-genai-naga-dev.svc:80
-> metrics are pushed to ai-tutor-quality-pushgateway
```

Required OpenShift secret:

- `ai-tutor-playwright-live-secret`

Required keys:

- `admin-email`
- `admin-password`
- `student-email`
- `student-password`

Create/update with placeholders:

```bash
oc create secret generic ai-tutor-playwright-live-secret \
  -n rit-genai-naga-dev \
  --from-literal=admin-email='<admin-or-instructor-email>' \
  --from-literal=admin-password='<admin-or-instructor-password>' \
  --from-literal=student-email='<student-email>' \
  --from-literal=student-password='<student-password>' \
  --dry-run=client -o yaml | oc apply -f -
```

## Report and Video

By default, `playwright.config.ts` keeps video on failure. OpenShift overrides this with:

```bash
PLAYWRIGHT_VIDEO=off
```

to reduce storage and runtime cost.

To keep local videos for passing tests:

```bash
export PLAYWRIGHT_VIDEO=on
npx playwright test
npx playwright show-report
```

## Common Failures

- Missing PDF: verify `PLAYWRIGHT_HOMEWORK_PDF_PATH` locally or `playwright/fixtures/Math_HW.pdf` in OpenShift.
- Login failure: verify account credentials and app auth behavior.
- No homework model: configure a workspace model whose name includes `homework` for the selected group.
- No chat model: configure a model visible to the student account.
- No assistant response: verify model routing and backend inference health.
- Dashboard inaccessible: verify route, permissions, and AI Tutor feature visibility for the account.

In OpenShift strict mode, these are failed deployed-environment checks because they prevent a real workflow from succeeding.
