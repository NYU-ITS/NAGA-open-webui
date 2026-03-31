# AI Tutor Frontend Cache and State Checklist

## Goal

The AI Tutor dashboard should feel stable and immediate during tab switches.

Tab switches should:
- read from session storage first
- render immediately from the last valid snapshot
- avoid clearing visible data during temporary URL or layout transitions

The frontend should only fetch from the server when:
- there is a cache miss
- cached data was explicitly invalidated
- the user has just completed a state-changing action

This document defines the expected cache, selection, and refresh behavior for the instructor and student AI Tutor flows.

## Core Principles

1. Group selection has a single source of truth.
- The only group switcher is the top `Your Groups` dropdown.
- All AI Tutor tabs must reuse the currently selected group.
- Tab navigation must preserve `group_id`.

2. UI should restore the last valid selection.
- Refreshing the page should not force the user to reselect the group.
- Refreshing the page should not force the user to reselect the homework.
- Each page should restore its last valid selection from session storage when possible.

3. Tab switches should prefer cached snapshots.
- Tab switches should not trigger visible blank states.
- Pages should render from session storage immediately if a valid snapshot exists.
- Pages should not clear existing state while `group_id` is temporarily pending.

4. Failed requests must not wipe valid UI state.
- If a background fetch fails, the previous valid data should remain visible.
- Empty or error states should not overwrite existing cached snapshots unless the server response is intentionally authoritative.

5. Server refresh should be explicit.
- The frontend should refetch only after cache miss, explicit invalidation, or a completed state-changing action.
- Conversation counts may remain a controlled exception with shorter TTL or lightweight refresh behavior.

## Expected Selection Behavior

### Group

- Selected group is controlled by the top dropdown only.
- Selected group should be represented in the URL via `group_id`.
- Switching tabs must preserve the current `group_id`.
- Reloading a page with a valid `group_id` should immediately restore that group context.

### Homework

- Each page with a homework filter should persist its selected homework in session storage.
- If the previously selected homework still exists in the current group data, it should be restored automatically.
- If the previously selected homework no longer exists, the page should fall back to:
  - `All Homeworks`, or
  - the first valid homework for that page

## Cache Strategy

### Session Storage Policy

Session storage should be used for:
- last selected group-aware page state
- last selected homework per page
- last successful API snapshots for each page
- active async job state needed for refresh recovery

### Recommended Cache Key Pattern

Use page- and group-scoped keys such as:

- `ai_tutor_session_cache:summary:{group_id}:homework-stats`
- `ai_tutor_session_cache:summary:{group_id}:error-types`
- `ai_tutor_session_cache:summary:{group_id}:tutor-prompts`
- `ai_tutor_session_cache:topic-analysis:{group_id}:analysis`
- `ai_tutor_session_cache:topic-analysis:{group_id}:practice`
- `ai_tutor_session_cache:student-analysis:{group_id}:homeworks`
- `ai_tutor_session_cache:student-analysis:{group_id}:analyses:{hash}`
- `ai_tutor_ui_state:{page}:{group_id}`

### What Should Be Cached

#### Summary
- homework rows
- homework-level analysis stats
- error types
- general prompts
- tutor prompts

#### Topic Analysis
- homework rows
- topic analysis grouped data
- practice question set rows
- error types
- sent-assignment timestamps

#### Student Analysis
- homework list
- group member roster
- all loaded analysis rows for the group
- selected homework filter

#### Instructor Setup
- workspace model candidates
- homework rows
- conversation counts
- prompts
- error types
- selected homework for run-analysis actions if applicable

#### Student Dashboard
- homework rows
- assignment rows
- practice rows
- analysis rows
- selected practice assignment if needed for recovery

## When to Fetch From the Server

### Allowed Automatic Fetches

The frontend may fetch from the server when:
- no valid cache exists
- the page has never loaded for the current group
- the cached snapshot has expired
- a page-specific selection points to data that is missing from cache

### Required Post-Action Refreshes

The frontend should invalidate and refetch after:

- homework PDF upload completed
- answer PDF upload completed
- conversation export completed
- analysis run completed
- practice generation completed
- practice re-generation completed
- practice approval completed
- practice send completed
- error type save/reset completed
- prompt save/reset completed

### Exception

Conversation counts may use:
- shorter TTL
- lightweight background refresh

This is acceptable because conversation activity can change outside the AI Tutor pipeline.

## What Must Never Be Cached as a Valid Snapshot

The frontend must not write these states into session cache as authoritative data:

- empty data caused by missing `group_id`
- empty data caused by layout transition timing
- empty data caused by temporary unauthorized state during startup
- failed fetch fallbacks
- partial state where required companion data has not loaded yet

## Page-by-Page Expected Behavior

### Summary

On tab switch:
- render cached homework stats immediately
- preserve the currently selected group
- do not blank charts or table while waiting for layout stabilization

Only refetch when:
- cache miss
- explicit invalidation after upload/run/save/reset
- conversation count refresh policy requires it

### Topic Analysis

On tab switch:
- render cached topic rows and practice rows immediately
- preserve current group
- preserve current homework filter if one exists

Only refetch when:
- cache miss
- explicit invalidation after generate/re-generate/send/error-type change

### Student Analysis

On tab switch:
- render cached homework list, student roster, and analysis rows immediately
- preserve selected homework

Only refetch when:
- cache miss
- explicit invalidation after analysis completion

### Instructor Setup

On tab switch:
- render cached workspace-model-derived homework candidates immediately
- preserve group
- preserve visible homework/action state

Only refetch when:
- cache miss
- explicit invalidation after upload/run/config changes

### Student Dashboard

On tab switch:
- render cached assignment and homework summaries immediately
- preserve selected group and practice context

Only refetch when:
- cache miss
- explicit invalidation after assign/send/analysis completion

## Refresh Recovery Requirements

Async jobs must be recoverable after refresh for:
- homework PDF upload
- analysis run
- practice generation

Recovery behavior:
- restore job status from local or session storage
- resume polling
- keep last valid page data visible
- replace cached snapshots only when the job completes successfully

## Current Gaps To Implement

1. Persist selected homework per page.
- Summary
- Topic Analysis
- Student Analysis
- Instructor Setup where applicable

2. Standardize page-level UI state keys.
- selected homework
- expanded/collapsed view preferences if needed

3. Prevent cache writes for transient empty states.

4. Preserve previous valid state on fetch failure across all instructor tabs.

5. Standardize invalidation helpers so all pages react to the same completed actions.

6. Confirm whether Student Dashboard should also persist the current practice assignment selection across refresh.

## Implementation Notes

- Comments in code should remain in English.
- Cache invalidation should be explicit and narrow by page/group prefix.
- The UI should prefer "stale but valid" over "blank but loading".
- Hard refresh should not be the normal way to recover visible data.

## Definition of Done

This checklist is implemented when:
- switching between AI Tutor tabs does not produce visible blank states
- group selection remains stable unless changed from the top dropdown
- homework selection restores automatically after refresh
- cached data renders instantly on tab switch
- server fetches happen only on cache miss or explicit invalidation
- completed actions correctly refresh only the affected data slices
