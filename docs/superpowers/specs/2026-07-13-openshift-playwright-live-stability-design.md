# OpenShift Playwright Live-Test Stability Design

**Status:** Approved for implementation planning

**Date:** 2026-07-13

## Summary

The Playwright tests that run against the deployed OpenShift development application are intermittently failing in Firefox and WebKit even though the equivalent tests pass against the local Docker deployment and the Chromium live path now passes. This work will address only the live custom-model tests and the AI Tutor dashboard live workflows.

The debugging evidence currently available points to browser readiness and asynchronous rendering races in addition to possible OpenShift network latency. In the captured custom-model failures, the requested model is present in the final accessibility snapshot, while the screenshot either shows the workspace still loading or shows the model card already rendered. The current model-card helper repeatedly navigates, performs immediate visibility probes, and eventually replaces the underlying failure with a one-millisecond assertion. This makes a slow render look like a missing model and obscures whether the delay came from navigation, the models API, Svelte rendering, or the locator itself.

The AI Tutor workflow has a related reliability risk: some setup and cleanup requests do not use the shared transient-request handling, and a failure partway through test-data creation can leave a group or model behind because ownership is returned to the test only after the entire setup completes.

The implementation will first reproduce and classify failures one spec and one browser at a time against the deployed application. Changes will then target the demonstrated synchronization, transient-request, diagnostic, and cleanup problems rather than masking failures with broad retries or global timeout increases.

## Goals

- Make the failing custom-model live tests reliable in Firefox and WebKit against the deployed OpenShift development application.
- Make the AI Tutor dashboard live workflows reliable in Firefox and WebKit against the same application.
- Distinguish browser-rendering delays, transient network failures, backend failures, and locator failures in test output.
- Ensure every model and group created by these tests is cleaned up, including after partial setup or a failed assertion.
- Preserve strict live checks so genuine application, authorization, inference, and pipeline failures still fail the tests.
- Retain Chromium coverage and behavior as a regression control.

## Non-goals

- Changing group UI tests or other Playwright suites.
- Changing application behavior solely to accommodate the tests unless diagnostics establish an application defect and a separate change is approved.
- Adding unconditional retries for all test actions.
- Treating every slow response as transient or converting strict live failures into skips.
- Rebuilding the OpenShift image during the initial debugging loop.
- Modifying `playwright.config.ts` without separate user approval.

## Scope

### In scope

- `playwright/tests/models/*.live.spec.ts`, limited to the custom-model workflows and failures exercised by those specs.
- `playwright/tests/ai-tutor-dashboard.live.spec.ts`.
- Shared Playwright fixtures directly used by those tests.
- Focused live verification against Firefox, WebKit, and Chromium.

### Explicit approval boundary

`playwright.config.ts` must not be modified as part of the initial implementation. If focused traces establish that a project-wide Playwright setting is necessary, work must pause and present:

1. the evidence that cannot be addressed within the scoped tests or fixtures;
2. the exact proposed configuration change;
3. the suites affected by that change; and
4. the expected trade-offs.

Implementation may proceed with that configuration change only after explicit user approval.

## Current evidence and working hypotheses

### Custom-model rendering

Preserved failure artifacts show Firefox failures for single-model export and JSON import, plus a WebKit failure for CRUD. The target model appears in the failure accessibility snapshots. One Firefox screenshot shows the workspace loading spinner, while the WebKit screenshot shows the target card already rendered.

The current `waitForModelCardInWorkspace` helper:

- repeatedly navigates to the models page;
- suppresses errors from the browser-side model request and splash-screen wait;
- uses immediate `isVisible()` probes instead of a web-first assertion;
- can spend most of its budget inside a small number of slow navigations;
- uses a text fallback whose first match can be hidden tooltip content; and
- reports a final one-millisecond visibility assertion rather than the last meaningful failure.

The primary hypothesis is that Firefox and WebKit expose a route/API/render scheduling race that Chromium happens to complete within the immediate probe. The first implementation experiment will replace that loop with bounded, observable response-and-render synchronization.

### OpenShift request latency

The deployed environment can produce transient connection failures and transient HTTP responses. The existing model and authentication fixtures already define bounded retry behavior for selected requests, but the AI Tutor spec duplicates authentication code and the user/group fixture does not use that retry boundary.

The working hypothesis is that only transport errors and HTTP 408, 429, 500, 502, 503, and 504 responses should be retried. Authentication, authorization, validation, and other deterministic failures must remain immediate failures.

### Cleanup and shared state

The current custom-model cleanup helper can delete every model with the shared `test-custom-models-` prefix. That can interfere with another live run and can also delete an AI Tutor model because both use the same prefix.

The model specs generally track one created ID and perform best-effort cleanup after each test, but cleanup errors are swallowed and deletion is not consistently verified. The AI Tutor setup creates a group before finishing model setup; if setup throws before returning its data object, the caller's `finally` block does not know what needs deletion.

The working hypothesis is that resource ownership must be registered as each resource is created, not after the full setup succeeds.

## File locations and responsibilities

| File | Intended responsibility |
| --- | --- |
| `playwright/fixtures/models.ts` | Model API operations, model visibility synchronization, model diagnostics, and targeted model cleanup. |
| `playwright/fixtures/auth.ts` | Shared sign-in behavior and bounded retry policy for transient authentication transport failures. |
| `playwright/fixtures/users.ts` | User/group API operations using the same bounded transient-request policy. |
| `playwright/tests/models/model-crud.live.spec.ts` | CRUD workflow assertions and registration of the model created by the test. |
| `playwright/tests/models/model-import-export.live.spec.ts` | Import/export workflow assertions and registration of models created or updated by each test. |
| `playwright/tests/models/model-access-control.live.spec.ts` | Access-control workflow cleanup and verification if focused reproduction identifies a failure here. |
| `playwright/tests/models/model-validation.live.spec.ts` | Validation workflow cleanup and verification if focused reproduction identifies a failure here. |
| `playwright/tests/ai-tutor-dashboard.live.spec.ts` | AI Tutor setup, route readiness, upload/pipeline diagnostics, chat workflow checks, and owned-resource cleanup. |
| `scripts/run_openshift_frontend_quality_checks.sh` | Existing deployed-run entry point; expected to remain unchanged unless the scoped verification reveals a runner-only defect. |
| `playwright.config.ts` | Explicitly excluded without a separate evidence-based approval request. |

## Debugging approach

### 1. Use the deployed application for the feedback loop

The initial loop will not rebuild the OpenShift test image. Each run will use the existing live-mode environment variables and credentials obtained from the OpenShift secret, then execute one test in one browser.

Representative test invocation:

```bash
PLAYWRIGHT_RUN_LIVE=1 \
PLAYWRIGHT_STRICT_LIVE_CHECKS=1 \
PLAYWRIGHT_SKIP_WEB_SERVER=1 \
PLAYWRIGHT_BASE_URL=https://opwn-webui-rit-genai-naga-dev.apps.cloud.rt.nyu.edu \
PLAYWRIGHT_ADMIN_EMAIL="$(oc get secret ai-tutor-playwright-live-secret -n rit-genai-naga-dev -o jsonpath='{.data.admin-email}' | base64 -d)" \
PLAYWRIGHT_ADMIN_PASSWORD="$(oc get secret ai-tutor-playwright-live-secret -n rit-genai-naga-dev -o jsonpath='{.data.admin-password}' | base64 -d)" \
PLAYWRIGHT_STUDENT_EMAIL="$(oc get secret ai-tutor-playwright-live-secret -n rit-genai-naga-dev -o jsonpath='{.data.student-email}' | base64 -d)" \
PLAYWRIGHT_STUDENT_PASSWORD="$(oc get secret ai-tutor-playwright-live-secret -n rit-genai-naga-dev -o jsonpath='{.data.student-password}' | base64 -d)" \
npx playwright test <spec> --project=<browser> --grep '<test name>' --retries=0 --trace=on
```

The first reproductions will be:

1. Firefox single-model export.
2. Firefox valid JSON import.
3. WebKit model CRUD.
4. Each AI Tutor workflow separately in Firefox and WebKit.

The first run of each case will use zero retries so a retry cannot hide the original transition. After a candidate fix passes once, `--repeat-each=3` will test whether it is stable rather than merely lucky.

### 2. Capture the boundary where the delay occurs

For each failure, diagnostics will identify:

- whether navigation completed;
- whether the workspace models request was sent;
- the response status or request failure;
- whether the page's loaded marker appeared;
- whether the API response contained the target model;
- whether the target model existed in the DOM;
- which exact locator was used; and
- whether a modal, toast, or loading overlay blocked interaction.

AI Tutor diagnostics will additionally cover sign-in, current-user lookup, group creation, model creation, dashboard data loading, PDF upload, pipeline status polling, and chat generation. Sensitive tokens and passwords must never be attached or logged.

### 3. Test one hypothesis at a time

The first change will address model-page readiness only. If that resolves the Firefox and WebKit custom-model reproduction, unrelated timeout or runner changes will not be made. If it does not, the next hypothesis will be based on the new trace and network evidence.

No more than one causal behavior will be changed between focused reproductions. After three unsuccessful fix hypotheses, implementation will pause for an architectural review instead of layering on another retry or timeout.

## Proposed design

### Model-card synchronization

`waitForModelCardInWorkspace` will become a bounded synchronization helper rather than a navigation loop with immediate probes. Each attempt will:

1. prepare observation of the relevant workspace models response;
2. navigate or reload the models route once;
3. confirm a successful response or record the specific transient failure;
4. wait for the models view to reach its loaded state; and
5. use a web-first assertion for the exact target card.

Retries will be bounded and will repeat the whole observable attempt only for an incomplete render or an identified transient request failure. The helper will not use `networkidle`, fixed sleeps as readiness signals, hidden tooltip text, or a synthetic one-millisecond terminal assertion.

If the model is visible through the API but not rendered, the failure attachment will say so explicitly and include the current page state. If the API does not contain it, the failure will remain an API-state failure.

### Transient API handling

The shared retry helper will be the single policy boundary for scoped Playwright API operations. AI Tutor sign-in and group/user operations will use it instead of direct unguarded requests.

Retry behavior will remain:

- bounded by a small number of attempts;
- exponential or otherwise increasing between attempts;
- limited to recognized transport errors and transient statuses; and
- observable in failure diagnostics.

Non-idempotent creation calls will use deterministic test resource identifiers. Before repeating a create after an ambiguous transport failure, the helper will check whether the resource already exists. This prevents a retry from creating duplicates.

### Resource ownership and cleanup

Each test will own a resource registry local to that test execution. A model or group will be registered immediately after its creation succeeds. Cleanup will run from `finally` or teardown in reverse dependency order:

1. delete the AI Tutor model;
2. verify the model is absent;
3. delete the group; and
4. verify the group is absent when an appropriate read endpoint is available.

Custom-model tests will delete only the IDs they created. The broad cleanup of every `test-custom-models-` resource will be removed from the per-test path because it is unsafe when runs overlap.

Cleanup will use bounded transient handling. If the test body passed and cleanup failed, the test will fail with cleanup diagnostics. If the test body already failed, the original failure will be preserved and cleanup failure details will be attached rather than replacing it.

### AI Tutor workflow readiness

The AI Tutor spec will reuse the shared authentication helper and will register its group and model during setup. Dashboard navigation will wait for both the expected route data and the semantic UI state required by the workflow.

The PDF upload workflow will continue distinguishing HTTP upload completion from pipeline completion. Its timeout will be increased only if traces show healthy pipeline progress that exceeds the current budget. An HTTP error, stalled poller, or request failure must remain a strict failure.

The student chat workflow will continue failing when inference reports an error. It will not be marked successful merely because the page loaded or the submit action completed.

## Error-handling principles

- Do not catch and discard information needed to identify the failing boundary.
- Do not retry deterministic 4xx failures other than an explicitly understood conflict whose postcondition is verified.
- Do not use arbitrary sleeps as the primary readiness mechanism.
- Do not hide a failing live dependency by skipping when strict live checks are enabled.
- Preserve the earliest causal failure and attach later cleanup problems separately.
- Never log credentials or bearer tokens.

## Verification

Verification will proceed from smallest to broadest:

1. The originally failing test passes once in its failing browser with a trace retained.
2. The same test passes three consecutive repetitions in that browser.
3. All custom-model live specs pass in Firefox.
4. All custom-model live specs pass in WebKit.
5. The AI Tutor dashboard live spec passes in Firefox.
6. The AI Tutor dashboard live spec passes in WebKit.
7. The scoped custom-model and AI Tutor tests pass in Chromium as regression coverage.
8. The development application contains none of the resources created by the verification run.

A passing test must reflect the intended assertion. Broad retries, swallowed errors, skipped strict checks, or cleanup that deletes another run's data do not satisfy verification.

## Success criteria

- The previously observed Firefox and WebKit custom-model failures cannot be reproduced in three consecutive focused runs.
- Each AI Tutor live workflow passes in Firefox and WebKit under strict live checks.
- Failures caused by an unavailable backend or pipeline still report the causal request/status and fail.
- Every test-created model and group is removed after both successful and failed runs.
- Concurrent or overlapping runs cannot delete each other's resources through prefix-wide cleanup.
- Chromium remains passing.
- No `playwright.config.ts` change is made without the required separate approval.

## Implementation constraints

- Preserve existing uncommitted user changes and reconcile implementation with them rather than overwriting them.
- Keep changes limited to the scoped specs and their directly used fixtures.
- Use the deployed application for focused debugging before rebuilding an OpenShift image.
- Follow current Playwright web-first assertion and trace practices.
- Stop and request approval before any proposed `playwright.config.ts` modification.
