# Multimodal embeddings branch comparison

Reviewed September 17, 2026.

**Recommendation: selectively port the useful fixes; do not merge `fix/multimodal-embeddings` wholesale.** The developer's claim is substantially correct: the branch contains useful reindexing and error-reporting fixes. However, its access-related work changes ownership policy, contains an ineffective projection filter, and targets an older indexing implementation.

## Scope and evidence

- Current branch: `feat/multimodal-embeddings`, reviewed at `067a93d705d9f7c659ed464fb2004ceacd1d3e98`.
- Compared branch: `fix/multimodal-embeddings`, at `003d9e0db046023f368c951ae9d1e062ad99c3f7`. Fetched from origin and confirmed that the local and remote target tips match.
- Common ancestor: `9d65037f2d4801694aaf9323dc09887c30adf4f7`.
- Divergence: 17 commits unique to the current branch; 6 unique to the fix branch. The fix branch changes 10 files relative to the common ancestor.
- Reviewed all six incoming commits and traced affected current inventory, resolution, publication, worker, retrieval metadata, and UI paths.
- `git merge-tree --write-tree --name-only HEAD fix/multimodal-embeddings` found content conflicts in `file_processing.py`, `inventory.py`, `knowledge_status.py`, and `worker.py`, all under `backend/open_webui/retrieval/embedding/`. This simulated a merge without changing working files or merging either branch.
- Static review only. No application or tests were run, in accordance with repository instructions. Deployment-specific queue consumers and production data were not inspected. The pre-existing `.gitignore` modification was left untouched; `.env` and `.env.local` were not read.

## Commit decisions

| Incoming commit | Change | Recommendation |
| --- | --- | --- |
| `e13b95861` | Scope inventory by source ownership | Rework together with the ownership portions of `3c447e043`; do not blindly cherry-pick. |
| `f09371899` | Display structured embedding-model errors | Port. Use a generic fallback for errors without a message, rather than always blaming model approval. |
| `3c447e043` | Align inventory, KB resolution/status, projections, and worker queues | Split it. Port the queue subscription; redesign the ownership changes and repair the projection filter. |
| `1ce06e0ef` | Remove re-import warning; display `N/A` before first success | No necessary fix remains: the warning is already absent; `Not yet` is already a valid, localized fallback. |
| `72bea52aa` | Add KB identity to reindex vector metadata | Covered for current model-aware pgvector retrieval by the newer publication/read path. No direct port needed for that path. |
| `003d9e0db` | Persist/display modality incompatibility errors | Port the behavior into the current per-file outcome path. Its old worker implementation no longer applies. UI labels are optional. |

## Important fixes to bring over

### 1. Subscribe the supplied RQ worker to reindex jobs — high priority

Current `embedding/enqueue.py` enqueues reindex jobs on `embedding_reindex`, but `workers/start_worker.py:286–292` creates a worker listening only to `FILE_PROCESSING_QUEUE_NAME`. The queue portion of `3c447e043` subscribes that worker to both queues.

With `ENABLE_JOB_QUEUE=true` and only this supplied worker entrypoint deployed, reindex jobs have no consumer on their queue. This does not affect the background-task execution mode, and a separately configured production worker might already cover the queue.

**Action:** port only the queue-related changes in `backend/open_webui/workers/start_worker.py`. Preserve the current dispatch, reconciliation, and publication implementation. Confirm the actual deployment has an `embedding_reindex` consumer.

### 2. Show structured model-update errors — medium priority

Current `src/lib/apis/retrieval/index.ts:267` assigns `err.detail` directly to the thrown error. The Documents UI interpolates that value into a toast (`Documents.svelte:170`). The backend emits structured details containing `error_code` and `message`, including queue-dispatch failures (`routers/retrieval.py:517`) and validation errors (`:543`). These can become `[object Object]` instead of actionable text.

**Action:** port `f09371899`'s extraction of `detail.message`. Improve its fallback: an unknown/network error should not be reported as an unapproved model. Preserve structured codes if callers need them.

### 3. Persist incompatibility feedback for file cards — medium priority

Current `embedding/worker.py:877` marks unsupported modalities in the job ledger, but that helper does not update `File.meta.processing_status` or its error fields. `FileItem.svelte:46–54` relies on those fields to show processing failures. Consequently, the reindex status can record an incompatible file while the file card retains stale processing information.

`003d9e0db` addresses this in the former finalization routine. That routine has been replaced by the current per-file publication architecture, so transplanting the old worker code is inappropriate.

**Action:** implement equivalent feedback in the current incompatibility outcome path, with ownership/generation safeguards so an obsolete job cannot overwrite a newer upload's state. Keep partial PDF visual warnings distinct from complete modality rejection: current code can publish usable PDF text while reporting unavailable visuals. The UI wording changes alone do not solve missing metadata.

## Ownership/access work: useful problem, unsafe implementation

### Current branch still has a governance mismatch

`inventory.py:488` resolves KB governance from access-control groups first. `resolution.py:88` instead resolves the KB owner through admin inheritance. A KB owned by admin A but shared with a group owned by admin B can therefore resolve to B for inventory/status/projection checks and A for upload/query model resolution. Multiple groups owned by different admins can also make inventory governance ambiguous.

Additionally, `_build_inventory` parses and resolves sources before filtering by the requested administrator (`inventory.py:733–770`). Malformed or unresolvable unrelated sources can therefore block another administrator's model change. Later missing-file checks are scoped, but these earlier failures are not.

**These issues deserve fixes.** Sharing permissions and embedding governance should have a consistent relationship across inventory, upload, retrieval, publication, and status.

### The incoming solution changes supported behavior

The fix branch includes only directly admin-owned KBs. Group access no longer determines governance; non-admin-owned KBs fail model-space resolution. It also excludes ordinary users' ungrouped chats from admin reindex inventories, while including grouped chats owned by that admin's group.

This is a policy change, not merely an authorization check. Current `routers/knowledge.py:400–420` allows permitted non-admin users to create KBs under their own ownership, and supports owner assignment by super administrators. Under the proposed resolver, such KBs can still exist but cannot resolve an embedding model space.

The branch does not alter the KB read-access check itself. Its main access-related change is who governs the embedding space, not a general read/write ACL repair.

**Action:** choose and document the ownership policy before porting it. A compatible option is owner-based governance with explicit support for non-admin owner inheritance, consistently applied everywhere. If direct-admin ownership is the intended product rule, creation/assignment behavior and existing non-admin-owned KBs need a migration or an explicit unsupported-state workflow. Scope eligible sources before strict parsing, and retain current targeted-retry and missing-source handling.

### Incoming projection filter is ineffective — blocker to taking it as-is

In the fix branch's `file_processing.py:533–569`, `_resolve_knowledge_projection_ids` first adds every KB referencing the file to `knowledge_ids`. For an owner outside the selected admin scope, lines 557–558 merely execute `continue`; they never remove the ID. The function returns the original set.

For a file referenced by KBs belonging to admins A and B, processing for A can therefore return both projection IDs. This contradicts the intended scope and removes the earlier fail-closed mismatch check. It is a cross-owner projection/integrity risk; this static review does not establish a user-visible data disclosure.

**Action:** construct the returned set only from eligible KBs, while retaining membership rechecks, row locking, and rejection of an explicitly requested out-of-scope KB. Do not copy this implementation unchanged.

### Current status code needs a coordinated port

The current generation snapshot still calls `resolver.resolve_knowledge` (`knowledge_status.py:383`), as does status construction (`:515`); the fix branch removes that resolver method. These newer callers must be adapted together. Current projection resolution uses it as well (`file_processing.py:650`). Resolving textual conflicts is insufficient.

Preserve the current branch's generation-aware publication coverage, retry accounting, `governing_admin_id`, canonical model names, and administrator-specific summary filtering from `ed8eb6322`. The fix branch's `in_reindex_scope=False` response also labels excluded KBs `ready` while setting `retrieval_available=False`; use an explicit unsupported/unavailable presentation instead of misleading readiness.

## Changes already covered or optional

**KB metadata parity (`72bea52aa`):** the current worker calls `publish_prepared_file`, which passes the collection's `knowledge_id` to vector construction (`publication.py:312–324`). `ModelAwareVectorRepository.make_items` stores that identity as provenance, and pgvector's `_result_metadata` injects it into returned metadata (`pgvector.py:171–187`). Both model-aware search and query use that helper (`:839`, `:976`). Thus the important retrieval behavior is already covered without the old worker patch. Stored JSON metadata is not identical to the fix branch's representation; any consumer bypassing these model-aware read methods should be checked separately if JSON parity is required.

**Status wording (`1ce06e0ef`):** the obsolete re-import warning is already gone. `ReindexStatusPanel.svelte:91–93` returns localized `Not yet` for a missing timestamp. Replacing it with hard-coded `N/A` is cosmetic.

## Suggested integration sequence

1. Port the queue subscription as a small independent fix.
2. Port structured error rendering with a neutral fallback.
3. Implement incompatibility feedback in the current worker outcome flow, preserving generation safety and partial-success behavior.
4. Implement one consistent governance policy across inventory, resolution, publication, retries, and status; repair the projection-set filtering rather than importing it.
5. Retain current metadata/read behavior and status wording unless a separate requirement calls for changes.

Before shipping those implementation changes, request Docker-based validation covering: queued reindex consumption; admin-owned KBs shared across admins; permitted non-admin KB ownership; grouped and ungrouped chats; malformed unrelated sources; one file shared across differently owned KBs; unsupported image/video inputs; partial PDF visuals; deleted-source retries; and KB retrieval after reindex. These are proposed checks, not tests performed during this review.

**Decision:** the branch should inform several focused fixes, but a full merge introduces unnecessary conflict resolution and an ownership regression risk. Selective ports plus a coordinated governance fix are the better integration route.
