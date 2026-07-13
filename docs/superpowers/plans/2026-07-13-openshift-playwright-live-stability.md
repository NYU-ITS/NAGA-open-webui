# OpenShift Playwright Live Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the scoped OpenShift live custom-model and AI Tutor Playwright workflows without weakening strict checks or changing `playwright.config.ts`.

**Architecture:** Centralize bounded transient-request policy in the existing auth fixture, then have model and group operations use it. Replace model-card navigation/probe loops with response-aware page readiness plus exact, web-first card assertions. Tests own IDs as soon as resources are created and clean them in reverse dependency order while preserving the original failure.

**Tech Stack:** TypeScript, Playwright APIRequestContext/Page assertions, deployed OpenShift application.

---

### Task 1: Establish a focused live-test baseline

**Files:**
- Modify: none
- Test: `playwright/tests/models/model-import-export.live.spec.ts`
- Test: `playwright/tests/models/model-crud.live.spec.ts`

- [ ] **Step 1: Obtain the existing OpenShift live-test credentials without printing them**

Run the focused commands from the approved design with `--retries=0 --trace=on`, assigning secret values only to environment variables.

- [ ] **Step 2: Run Firefox single-model export and JSON import separately**

Run: `npx playwright test playwright/tests/models/model-import-export.live.spec.ts --project=firefox --grep 'exports a single model|imports valid JSON' --retries=0 --trace=on`

Expected: record the first causal failure boundary (models response, loaded UI, or exact card), retaining trace artifacts.

- [ ] **Step 3: Run WebKit CRUD separately**

Run: `npx playwright test playwright/tests/models/model-crud.live.spec.ts --project=webkit --grep 'lists and deletes' --retries=0 --trace=on`

Expected: record the first causal failure boundary and retain the trace.

### Task 2: Make model-page synchronization observable and exact

**Files:**
- Modify: `playwright/fixtures/models.ts`
- Test: `playwright/tests/models/model-crud.live.spec.ts`
- Test: `playwright/tests/models/model-import-export.live.spec.ts`

- [ ] **Step 1: Write a focused fixture-level test or extend an existing mocked spec for response-aware readiness**

Create coverage that proves an awaited models response followed by a delayed DOM render resolves the exact `#model-item-<id>` locator, and that an API-visible/non-rendered model includes diagnostics. Do not accept hidden text matches.

- [ ] **Step 2: Run the new test and confirm it fails against the current immediate-probe/navigation-loop behavior**

Run the smallest Playwright test command for the new test.

Expected: FAIL because the current helper probes visibility immediately or relies on text fallback.

- [ ] **Step 3: Implement a bounded observable attempt in `waitForModelCardInWorkspace`**

Prepare `page.waitForResponse` for `/api/v1/models/`, navigate/reload once, record status/request failure, wait for the models UI loaded marker, optionally filter with the search field only after it is visible, and assert the exact ID locator with `expect(locator).toBeVisible()`. Retry only an incomplete render or recognized transient request failure; attach diagnostics before throwing the last meaningful error.

- [ ] **Step 4: Remove unsafe fallback and synthetic terminal assertion**

Delete the hidden-tooltip text locator and the one-millisecond final assertion. The thrown error must identify the last response/render condition.

- [ ] **Step 5: Run fixture and scoped mocked regression tests**

Run: `npx playwright test playwright/tests/models/model-crud.mocked.spec.ts playwright/tests/models/model-import-export.mocked.spec.ts`

Expected: PASS.

### Task 3: Centralize transient request handling and safe resource cleanup

**Files:**
- Modify: `playwright/fixtures/auth.ts`
- Modify: `playwright/fixtures/models.ts`
- Modify: `playwright/fixtures/users.ts`
- Test: scoped mocked or fixture-level tests added under `playwright/tests/models/`

- [ ] **Step 1: Write failing tests for retry policy and cleanup postconditions**

Cover retrying only transport errors and 408/429/500/502/503/504, returning deterministic 4xx without retry, and verifying model/group deletion is observed after cleanup.

- [ ] **Step 2: Run those tests and confirm expected failures**

Run the test file containing the new cases.

Expected: FAIL because group/current-user calls bypass the shared retry boundary and cleanup does not consistently verify deletion.

- [ ] **Step 3: Make all scoped user/group calls use `retryApiRequest`**

Wrap `getCurrentUser`, `createGroupViaAPI`, and `deleteGroupViaAPI`; preserve immediate failure for deterministic statuses. For ambiguous non-idempotent creation, check the deterministic resource name before retrying creation.

- [ ] **Step 4: Replace prefix-wide cleanup with owned-ID cleanup**

Remove `cleanupTestModelsViaAPI` from every per-test path. Ensure tests register IDs at creation, delete only those IDs, and await absence. If the test body already failed, attach cleanup diagnostics without replacing its error; otherwise surface cleanup failure.

- [ ] **Step 5: Re-run cleanup and retry coverage**

Run the newly added focused tests.

Expected: PASS.

### Task 4: Refactor AI Tutor setup and workflow readiness

**Files:**
- Modify: `playwright/tests/ai-tutor-dashboard.live.spec.ts`
- Modify: `playwright/fixtures/auth.ts`
- Modify: `playwright/fixtures/users.ts`
- Test: `playwright/tests/ai-tutor-dashboard.live.spec.ts`

- [ ] **Step 1: Write a failing test for partial setup ownership**

Cover model creation failing after group creation and assert the group is still registered for cleanup. Cover a successful cleanup verifying model absence before group deletion.

- [ ] **Step 2: Run the focused test and confirm it fails with the existing all-or-nothing setup return value**

Run the smallest test command for the new ownership coverage.

Expected: FAIL because `createAITutorTestData` does not return ownership until all setup completes.

- [ ] **Step 3: Reuse shared sign-in and register resources immediately**

Replace local duplicated sign-in/login functions with auth fixture exports. Use a local resource registry populated immediately after group/model creation and clean it in reverse dependency order in `finally`.

- [ ] **Step 4: Make dashboard readiness semantic and diagnostic**

For each dashboard route, wait for route data and the workflow’s semantic UI marker. Preserve upload HTTP/pipeline distinction and strict chat inference failures; attach request/status diagnostics without credentials.

- [ ] **Step 5: Run the AI Tutor focused test coverage**

Run: `npx playwright test playwright/tests/ai-tutor-dashboard.mocked.spec.ts`

Expected: PASS.

### Task 5: Live stability verification and cleanup audit

**Files:**
- Modify: none unless a scoped test exposes a demonstrated defect
- Test: scoped live specs

- [ ] **Step 1: Run each original failure once with trace**

Run Firefox export/import and WebKit CRUD with strict live variables, `--retries=0 --trace=on`.

- [ ] **Step 2: Repeat each repaired focused case three times**

Run each focused command with `--repeat-each=3`.

Expected: all repetitions pass without broad retries.

- [ ] **Step 3: Run scoped browser suites**

Run all custom-model live specs in Firefox, WebKit, and Chromium, then run AI Tutor live workflows in Firefox, WebKit, and Chromium.

- [ ] **Step 4: Audit test-created resources**

Use authenticated API reads to confirm IDs created by the verification run no longer exist. Do not delete prefix-matched resources that were not registered by the run.

- [ ] **Step 5: Review diff boundaries**

Run: `git diff --check` and `git diff -- playwright.config.ts`.

Expected: no whitespace errors; no implementation modification to `playwright.config.ts`.
