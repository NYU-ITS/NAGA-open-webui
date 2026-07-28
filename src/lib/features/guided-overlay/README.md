# Guided Overlay

This folder contains the role-based onboarding overlay implementation.

## Implementation Decision

The feature is designed as a mostly new-file implementation with minimal integration edits.

New files own:

- Overlay UI
- Student, Admin, and Super Admin guide configuration
- Role, group, permission, and feature context loading
- Condition filtering
- Cross-route navigation
- Target waiting and fallback
- Progress persistence and guide versioning

Existing files should only provide integration points:

- App layout renders `GuideHost`
- Help menu dispatches the restart event
- A small number of target elements receive stable `data-guide` attributes

## Step 1 Completed

The first implementation step added the feature foundation without wiring it into the app runtime.

Added:

- `types/guide.types.ts` for shared guide contracts
- `config/target-registry.ts` for logical target IDs
- `config/guide-registry.ts` and `config/guide.constants.ts`
- Student, Admin, and Super Admin guide definitions
- Context adapters for user, group, and feature resolution
- Condition, navigation, target, progress, and controller services
- Svelte store for runtime guide state
- Generic overlay components

No existing business logic is changed by this step.

## Step 2 Completed

The second implementation step added stable guide anchors to existing UI elements.

Added `data-guide` attributes for:

- Sidebar root: `sidebar`
- Sidebar toggle button: `sidebar-toggle`
- Sidebar New Chat: `new-chat`
- Sidebar conversation history: `conversation-history`
- Main chat/workspace container: `main-workspace`
- Model selector trigger: `model-selector`
- File upload / input menu entry: `file-upload`
- Input tools menu: `chat-tools-menu`
- Web Search toggle: `web-search`
- Code Interpreter toggle: `code-interpreter`
- Voice Input button: `voice-input`
- Call button: `call-button`
- Chat Controls button: `chat-controls`
- Help button: `help-menu`
- Admin users entry: `admin-panel`
- Existing AI Tutor Dashboard group selector: `admin-group-selector`
- Admin groups tab: `group-management`
- Admin functions page: `admin-functions`
- Admin documents settings tab: `admin-documents-tab`
- Admin documents settings section: `admin-documents-settings`
- Workspace models tab: `admin-models`
- Workspace knowledge tab: `admin-knowledge`
- Workspace tools tab: `admin-tools`
- Admin settings tab: `admin-modules`
- Create Knowledge button: `create-knowledge`
- Create Model button: `create-model`

These attributes are passive anchors only. They do not change routing, permissions, click handlers, or rendering logic.

## Step 3 Completed

The third implementation step connected the feature to the app with minimal integration edits.

Added:

- App layout renders `GuideHost`.
- Help menu includes `Start Guided Tour`.
- Help menu restart dispatches `guided-overlay:start`.

The Help menu entry does not depend on internal component state. It emits a browser event, and `GuideHost` delegates the restart to `guidedOverlayController.startGuide({ source: 'help-menu', force: true })`.

`GuideHost` is only mounted for active `user`, `admin`, and `super_admin` sessions, and is not mounted while the local chat migration modal is blocking the app.

## Step 4 Validation

Foundation validation started after the initial integration.

Completed checks:

- Inspected `package.json`, `docker-compose.local.yaml`, `Makefile`, `Dockerfile`, and GitHub workflows to identify the existing validation path.
- Ran `docker compose -f docker-compose.local.yaml config`.
- Ran `docker compose -f docker-compose.local.yaml build open-webui`.
- Confirmed Dockerfile frontend build completed successfully through `npm run build`.
- Confirmed `git diff --check` passes.

Build result:

```text
Image ghcr.io/open-webui/open-webui:main Built
```

Important notes:

- The Docker build produced existing Svelte/Vite warnings from unrelated files, including accessibility warnings and unused export warnings.
- No fatal error was reported from the guided overlay files.
- `npm run check` / `svelte-check` was not run on the host because this project requires Docker-only local workflows.
- The current `docker-compose.local.yaml` service builds the production image and does not provide a dedicated Node validation service for running `npm run check` against source files.
- Backend import checks were not run because this feature only changed frontend/Svelte/TypeScript files.

Validation fixes made during Step 4:

- Moved the restart event name into `GUIDE_START_EVENT`.
- Included `super_admin` in the app layout mount guard and context loader guard.
- Added `targetPolicy: "required" | "optional" | "deferred"` to guide steps.
- Made Student first 4 steps required targets.
- Kept optional/deferred targets skippable.
- Stopped guessing the first group as the current group when multiple groups exist.
- Made API-backed progress the source of truth when `/user/settings` loads successfully, with localStorage only as fallback.

## Step 5 Student Overlay UI

The fifth implementation step focuses only on the Student guide.

Added:

- Purple target outline around the active Student guide target.
- Compact guide tooltip with 1-2 sentence intro text.
- `Skip`, `< Back`, and `Next >` / `Finish` navigation controls.
- Student-specific targets for Model Selector, Message Input, Add Content, Tools Menu, Web Search, Code Interpreter, Voice Input, Call, Chat Controls, and Help.
- Student guide copy tuned to short, user-facing explanations.
- Sidebar guide copy now targets the three-line menu button as the expand/collapse control instead of the full side panel.
- Tools Menu is included when the visible tools button exists, so Research Facilities and Practice Questions are covered in the Student flow.
- Voice Input is anchored to the microphone button.
- Call is anchored to the headphone button.
- The tooltip and guide controls were visually polished with larger rounded corners, translucent glass styling, softer shadows, and rounded navigation buttons.
- The guide window was reduced in width, padding, font size, and button size so bottom-row targets stay visible.
- Tooltip positioning now uses the rendered guide window size and chooses a non-overlapping placement when the preferred placement would cover the target.
- The active target outline now uses a white inner outline plus purple outer ring so it remains visible on both the purple sidebar and white workspace.
- The separate Student `Main Workspace` step was removed to keep the student tour focused on actionable controls.
- The guide tooltip now includes a code-rendered mascot/sun mark and updated Student copy while keeping the existing purple color system and navigation button styling.
- Student tooltip content now follows the compact mascot-and-message layout from the design reference, with shorter action-oriented copy and low-emphasis step text.
- Message Input is now a dedicated Student step that highlights only the text entry row instead of the full workspace.
- Student now ends with a summary window that is not attached to a page target and offers `Back`, `Restart`, and `Finish`.
- The sidebar menu step now prefers the visible three-line button inside the expanded purple sidebar before falling back to the collapsed top navbar button.
- Visible target preference in `guide-target.service.ts`, so duplicated/off-screen targets do not steal the purple outline from the visible Student UI.
- Sidebar toggle anchoring for the Student side panel step when the sidebar is collapsed.
- Larger tooltip positioning buffer, so top-placed tooltips do not cover input-row targets such as Add Content and Web Search.
- Bottom placement for the top-right New Chat target, so viewport clamping does not push the tooltip over the purple target outline.
- The hidden/collapsed Conversation History step is not included in the Student guide until sidebar expansion behavior is implemented.

Admin and Super Admin guide content is intentionally not expanded in this step.

Validation:

- `git diff --check` passes.
- `docker compose -f docker-compose.local.yaml build open-webui` completed successfully.
- The Dockerfile frontend build completed successfully through `npm run build`.
- The local preview container was restarted from the newly built image.
- Latest preview returned `HTTP/1.1 200 OK` from `http://localhost:3000`.
- A local preview Student account was created through the existing admin APIs for browser validation.
- Earlier Docker-contained Playwright validation completed against the local preview Student account.
- Earlier screenshots confirmed the purple target outline, compact intro tooltip, `Skip`, `< Back`, and `Next >` controls rendered as expected.
- After removing Main Workspace and adding Message Input, Course Tools, Voice Input, and Call, the current preview account should see 12 Student steps when the same targets are available.
- Browser re-validation is still needed for the newly added Message Input, Course Tools, Voice Input, and Call steps.

Student preview note:

- The local preview Student account has `role=user`, so `resolveGuideRole` maps it to the Student guide.
- The guide starts with the first visible Student step, then moves through the Student chat interface targets.

Runtime preview status:

```text
docker compose -f docker-compose.local.yaml run -d --service-ports \
  -e DATABASE_URL=sqlite:////app/backend/data/webui.db \
  -e VECTOR_DB=chroma \
  open-webui
```

The preview container started successfully and serves the app at:

```text
http://localhost:3000
```

The default local compose startup was not used for this preview because the configured host PostgreSQL connection rejected the `postgres` user's password. The SQLite/Chroma override is only a local preview workaround and does not change source code or project configuration.

Still pending validation:

- First-login auto start.
- Help menu restart while guide is closed and while guide is already open.
- Persistence behavior for Finish, Skip, and Dismiss.
- Sidebar expanded Conversation History behavior.
- Cross-route Admin behavior.

## Step 6 Admin Overlay

The sixth implementation step reorders the Admin guide around the requested setup and chat-validation flow.

Added:

- Admin guide now starts with the three-line menu button, so admins understand how to expand or collapse the side panel.
- Admin Panel entry step opens the account menu and highlights `Admin Panel` as the starting point for admin setup.
- Functions step opens `/admin/functions` and explains where API-backed tools, API keys, and function settings are managed.
- Documents step opens `/admin/settings`, switches to the Documents tab, and explains document settings such as the embedding model name.
- Workspace step explains that admins use Workspace to manage Models, Knowledge, Prompts, and Tools.
- Admin group context reuses the existing AI Tutor Dashboard group selector. No new sidebar group UI is added.
- The Admin group selector anchor prefers the visible selector trigger, so the highlight covers the full selector text and chevron.
- Usage / Monitoring step highlights the existing AI Tutor Dashboard summary section and explains token usage, cost estimates, and activity metrics where available.
- Knowledge Base step opens `/workspace/knowledge`, highlights both the top `Knowledge` tab and the right-side `+` button, and positions the guide window near the `+` button.
- Model step opens `/workspace/models`, highlights both the top `Models` tab and the right-side `+` button, and positions the guide window near the `+` button.
- Main chat validation steps cover New Chat, model selection, query typing, Add Content, Course Tools, Web Search, Code Interpreter, Voice Input, Call, Chat Controls, and Help.
- Admin now ends with a summary window that is not attached to a page target and offers `Back`, `Restart`, and `Finish`.
- Stable section anchors were added for Admin Functions, Admin Documents settings, Create Knowledge, Create Model, and the existing AI Tutor Dashboard group selector.
- The overlay now observes target resize/layout changes, so highlights update after route changes or async content loads.
- Guide steps can now render multiple target highlights while keeping the guide window anchored to the primary target.
- Cross-route Admin steps wait briefly for the destination target to settle, then resolve the target again before drawing the highlight.
- Prioritized target lookup now selects the top Workspace `Models` and `Knowledge` tabs before page-section fallbacks.
- Admin guide version was bumped to `1.33` so saved progress from earlier Admin previews does not hide the updated flow.

Validation:

- `git diff --check` passes.
- A targeted trailing-whitespace scan passed for the guided-overlay files and the Admin section-anchor files changed in this step.
- The Admin tooltip was tightened for narrow viewports so the first step does not cover the sidebar group target.
- Cross-route Admin steps now show an opening/finding state while the guide navigates.
- Admin target scrolling now snaps to the destination immediately so the tooltip does not lag behind route changes or scroll movement.
- Guide steps can run `beforeTargetActions`, so the Admin guide can automatically open the side panel, account menu, and Documents tab before highlighting the next target.
- Admin cross-route steps use real page targets and direct route changes instead of extra transition-only cards.
- Models and Knowledge are separate Workspace pages in this version because the requested flow includes creating a Knowledge Base and creating a Model.
- Group Management is intentionally omitted from this Admin version because it is outside the current requested sequence.

## Runtime Flow

```text
GuideHost
-> load guide context
-> resolve role-specific guide
-> filter steps by permissions/features/group state
-> load saved progress
-> auto-start, resume, or stay idle
-> prepare route
-> wait for DOM target
-> show overlay
-> save progress on Next, Back, Skip, Dismiss, Restart, Finish
```

## Progress Storage

Progress is saved under the existing `/user/settings` API using:

```json
{
  "guided_overlays": {
    "student-onboarding": {
      "guideId": "student-onboarding",
      "guideVersion": "1.12",
      "role": "student",
      "status": "completed",
      "updatedAt": "2026-07-13T18:00:00.000Z"
    }
  }
}
```

The repository also writes a localStorage fallback so progress is not lost if the settings API is temporarily unavailable.

## Next Steps

1. Validate the Student guide in a real student browser session, especially Course Tools and Call.
2. Validate Finish, Skip, Dismiss, refresh, and Help menu restart persistence.
3. Tune target fallback behavior for hidden dropdown-only Student targets.
4. Validate the Admin guide in a real admin browser session, especially cross-route navigation and group tab selection.
5. Validate Usage / Monitoring against environments where token, cost, or activity metrics are enabled.
