
# Project Title

A brief description of what this project does and who it's for

# Playwright E2E (AI Tutor)

This repo uses **Playwright** for browser-level testing of the AI Tutor UI.

There are two kinds of tests:

- **Mocked UI tests**: run fast and do *not* require a real backend.
- **Live workflow bots**: drive a real local deployment and validate end-to-end flows.

## What files to look at

- `playwright/tests/ai-tutor-dashboard.mocked.spec.ts`
  - Mocked UI coverage for the AI Tutor dashboard pages.
- `playwright/tests/ai-tutor-dashboard.live.spec.ts`
  - Live workflow bots (admin + student flows).

## First-time setup (once per machine)

Install Playwright browsers:

```bash
npx playwright install
```


## HTML report and video

By default, `playwright.config.ts` uses `video: 'retain-on-failure'`, so the HTML report only keeps **recordings for failed tests** (to save disk space). To keep a video for **passing** tests too, run with:

```bash
export PLAYWRIGHT_VIDEO=on
npx playwright test
npx playwright show-report
```

Set `PLAYWRIGHT_VIDEO=off` to disable video entirely.

## Prerequisites for LIVE workflow bots

The live tests are real browser automation. They assume your local app is usable by a human first.

- **Running web app**: `PLAYWRIGHT_BASE_URL` must point at a running OpenWebUI instance (ex: `http://localhost:8080`).
- **Running AI Tutor backend**: It will be directly accessed from frontend
- **A Homework PDF Path**: A path to the Homework PDF must be provided so that the workflow can upload it for testing. See below for env vars.
- **Two real accounts**:
  - **Admin/Instructor user** (can access AI Tutor dashboard + upload homework PDF)
  - **Student user** (can open chat and send a message)
- **AI Tutor group exists and is selectable**
  - The admin user must be able to select the group from the “Select group” dropdown.
- **Homework model exists for the group**
  - The UI requires a workspace model whose name includes `"homework"` for the upload section to appear.
  - On slow loads, the page can briefly show **“No homework models are found for this group.”** while workspace models are still fetching; the live test **waits** for that to clear instead of skipping immediately.


## What each LIVE workflow does 

The live workflows are defined in `playwright/tests/ai-tutor-dashboard.live.spec.ts`.

### Workflow 1 (Admin) Upload homework PDF

Goal: verify an admin/instructor can reach Instructor Setup and upload a homework PDF.

Steps:

1. Log in via API (`/api/v1/auths/signin`) and inject the token into `localStorage`.
2. Open `"/aitutordashboard/instructorsetup"`.
3. Close the “What’s New…” modal if it’s visible.
4. Expand the **“2. Homework & Answer Files”** section if collapsed.
5. Clear any old visible toasts from page load so they do not get mistaken for this upload attempt.
6. In the **Homework PDF** column for the homework model row, set the PDF on the hidden input `#upload-question-…` (same as the purple upload icon). That fires the real upload; the Action column **Upload** button only appears when status is still “Upload Homework PDF” — after an upload, Action shows **Run** / **Re-run**, but replacing the PDF still uses this column’s file input.
7. Wait for **real completion**: a success toast **“Homework upload completed.”** (the pipeline can show **“Processing PDF”** in the row for a long time; that alone is not success). If an **error** toast appears after this upload starts, the test **fails** with that message.

### Workflow 2 (Student) Send a chat message

Goal: verify a student can send a chat message and see an assistant response start.

Steps:

1. Log in via API and inject the token into `localStorage`.
2. Open `"/"` (chat page).
3. Close the “What’s New…” modal if it’s visible.
4. If the UI shows **“Select a model”**, pick the first available model.
5. Type a message into `#chat-input`.
6. Click `button[type="submit"]`.
7. Wait up to 60s for either:
   - an assistant message bubble (`.chat-assistant`), or
   - a clear error toast.

### Workflow 3 (Admin) Open analytics dashboard

Goal: verify an admin can reach analytics and key UI elements render.

Steps:

1. Log in via API and inject the token into `localStorage`.
2. Open `"/aitutordashboard/topicanalysis"`.
3. Close the “What’s New…” modal if it’s visible.
4. Assert:
   - heading “Topic Analysis by Homework” is visible
   - “Practice Question” link is visible

## How to run

### Mocked UI tests (no backend required)

```bash
npm run test:e2e:ui -- playwright/tests/ai-tutor-dashboard.mocked.spec.ts
```

### Live workflow bots (requires a running app + real accounts)

Export env vars and run:

```bash

export PLAYWRIGHT_RUN_LIVE=1
export PLAYWRIGHT_BASE_URL="http://localhost:8080"

export PLAYWRIGHT_ADMIN_EMAIL="admin@example.com"
export PLAYWRIGHT_ADMIN_PASSWORD="password"

export PLAYWRIGHT_STUDENT_EMAIL="student@example.com"
export PLAYWRIGHT_STUDENT_PASSWORD="password"

export PLAYWRIGHT_HOMEWORK_PDF_PATH="/absolute/path/to/homework.pdf"

# If you need to force Playwright to use local browsers:
export PLAYWRIGHT_BROWSERS_PATH=0

# If you want to only run for the chromium browser, else remove --project to test on all 3 browsers.
npm run test:e2e:ui -- --project=chromium playwright/tests/ai-tutor-dashboard.live.spec.ts
```

Workflow 1 uses **only** the PDF configured by `PLAYWRIGHT_HOMEWORK_PDF_PATH`. If macOS blocks the configured path (commonly files in `~/Downloads`), the test fails with a clear PDF access error. Move the PDF somewhere this terminal can read (for example inside the repo or another non-protected folder) and point `PLAYWRIGHT_HOMEWORK_PDF_PATH` there.

Other useful modes:

- Headed UI (watch it run): `npm run test:e2e:ui:headed -- playwright/tests/ai-tutor-dashboard.live.spec.ts`
- Debug: `npm run test:e2e:ui:debug -- playwright/tests/ai-tutor-dashboard.live.spec.ts`

## Notes / common skips

Some skips indicate environment prerequisites, not a test bug:

- **No homework models found**: create/enable a workspace model whose name contains `"homework"` for the selected group.
- **No chat models**: configure at least one model for chat (and ensure the student can see it).
- **No assistant response**: inference backend may be slow/misconfigured; the test will skip rather than fail when it cannot confidently assert success.

