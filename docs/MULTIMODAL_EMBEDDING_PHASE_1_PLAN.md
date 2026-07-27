  # Phase 1 — Embedding Schema with Existing Config-Based Admin Settings

  ## Summary

  Preserve the current storage contract:

  - Per-admin model: admin’s config row at data.rag.embedding_model_user.
  - Platform default: global system@default row at data.rag.embedding_model.
  - Group inheritance: resolve the group owner through group.user_id, obtain that admin’s email, then read their existing config
    value.

  - Snapshot default: when an admin is created or promoted, copy the current global default into their config if they have not
    selected a model.

  Phase 1 will not add admin_embedding_settings or embedding_platform_settings. It will add the model registry, chunk/job
  schema, and model/admin provenance to the existing vector table.

  ## Config Storage Behavior

  ### Existing JSON remains authoritative

  Example global row:

  {
    "rag": {
      "embedding_model": "@openai-embedding/text-embedding-3-small"
    }
  }

  Example admin row:

  {
    "rag": {
      "embedding_model_user": "@openai-embedding/text-embedding-3-small"
    }
  }

  Phase 1 will:

  - Preserve existing nonempty admin values that match an enabled registry model.
  - Fill missing or empty admin values from the global default.
  - Continue exposing the existing RAG_EMBEDDING_MODEL_USER.get(email) and .set(email, value) behavior.
  - Validate model names against embedding_models before accepting changes.
  - Stop using arbitrary first-group ordering when resolving inherited settings in Phase 2; storage remains unchanged, but
    inheritance becomes context-specific and deterministic.

  - Ensure an admin email change moves the associated config row to the new email in the same transaction.
  - Ensure admin creation or promotion creates/configures the per-email row.
  - Retain the config row on demotion and remove it when the user is deleted.

  Because JSON cannot have a foreign key to embedding_models, registry integrity will be enforced by the config service and
  reconciliation checks.

  ## SQL Changes

  ### Existing config table

  No new column is required.

  Verify or add:

  CREATE UNIQUE INDEX IF NOT EXISTS ux_config_email_version
  ON config (email, version);

  Before creating the index, fail the migration preflight if duplicate (email, version) rows exist; do not automatically merge
  potentially unrelated configuration JSON.

  ### embedding_models

  CREATE TABLE embedding_models (
      id TEXT PRIMARY KEY,
      provider VARCHAR(64) NOT NULL,
      model_name TEXT NOT NULL UNIQUE,
      display_name TEXT NOT NULL,
      dimension INTEGER NOT NULL CHECK (dimension > 0),
      modalities JSONB NOT NULL,
      status VARCHAR(16) NOT NULL
          CHECK (status IN ('enabled', 'disabled', 'deprecated')),
      created_at BIGINT NOT NULL,
      updated_at BIGINT NOT NULL
  );

  Seed:
  
  | Field            | Value                                               |
  | ---------------- | --------------------------------------------------- |
  | **id**           | `embmdl-portkey-openai-text-embedding-3-small-1536` |
  | **provider**     | `portkey`                                           |
  | **model_name**   | `@openai-embedding/text-embedding-3-small`          |
  | **display_name** | `OpenAI text-embedding-3-small`                     |
  | **dimension**    | `1536`                                              |
  | **modalities**   | `["text"]`                                          |
  | **status**       | `enabled`                                           |

  model_name is globally unique because config stores that string rather than a registry ID.

  ### rag_chunks

  CREATE TABLE rag_chunks (
      id TEXT PRIMARY KEY,
      admin_id TEXT NOT NULL
          REFERENCES "user"(id) ON DELETE CASCADE,
      file_id TEXT NOT NULL
          REFERENCES file(id) ON DELETE CASCADE,
      chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
      content TEXT,
      content_type VARCHAR(16) NOT NULL
          CHECK (content_type IN ('text', 'image')),
      chunk_metadata JSONB,
      content_sha256 CHAR(64) NOT NULL,
      created_at BIGINT NOT NULL,
      updated_at BIGINT NOT NULL,
      UNIQUE (admin_id, file_id, chunk_index)
  );

  CREATE INDEX ix_rag_chunks_admin_file
  ON rag_chunks (admin_id, file_id);

  CREATE INDEX ix_rag_chunks_file_hash
  ON rag_chunks (file_id, content_sha256);

  Do not add knowledge_id: knowledge.data.file_ids remains authoritative, allowing one physical file/chunk set to be reused
  without duplication.

  ### embedding_jobs

  CREATE TABLE embedding_jobs (
      id TEXT PRIMARY KEY,
      admin_id TEXT NOT NULL
          REFERENCES "user"(id) ON DELETE CASCADE,
      embedding_model_id TEXT NOT NULL
          REFERENCES embedding_models(id) ON DELETE RESTRICT,
      previous_embedding_model_id TEXT
          REFERENCES embedding_models(id) ON DELETE RESTRICT,
      job_type VARCHAR(32) NOT NULL
          CHECK (job_type IN (
              'initial_index',
              'reindex_model_change',
              'retry_failed'
          )),
      status VARCHAR(24) NOT NULL
          CHECK (status IN (
              'queued',
              'processing',
              'completed',
              'failed',
              'partially_failed'
          )),
      total_files INTEGER NOT NULL DEFAULT 0 CHECK (total_files >= 0),
      processed_files INTEGER NOT NULL DEFAULT 0 CHECK (processed_files >= 0),
      failed_files INTEGER NOT NULL DEFAULT 0 CHECK (failed_files >= 0),
      rq_job_id TEXT UNIQUE,
      created_by_user_id TEXT
          REFERENCES "user"(id) ON DELETE SET NULL,
      error_message TEXT,
      created_at BIGINT NOT NULL,
      updated_at BIGINT NOT NULL,
      started_at BIGINT,
      completed_at BIGINT
  );

  CREATE UNIQUE INDEX ux_embedding_jobs_admin_active
  ON embedding_jobs (admin_id)
  WHERE status IN ('queued', 'processing');

  CREATE INDEX ix_embedding_jobs_admin_created
  ON embedding_jobs (admin_id, created_at DESC);

  A later model-change transaction must update the admin’s config JSON and insert the job using one database session. The
  existing UserScopedConfig.set() implementation must therefore gain a transaction-aware internal path rather than committing
  independently.

  ### embedding_job_files

  CREATE TABLE embedding_job_files (
      job_id TEXT NOT NULL
          REFERENCES embedding_jobs(id) ON DELETE CASCADE,
      file_id TEXT NOT NULL
          REFERENCES file(id) ON DELETE CASCADE,
      status VARCHAR(20) NOT NULL
          CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
      attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
      error_code VARCHAR(64),
      error_message TEXT,
      created_at BIGINT NOT NULL,
      updated_at BIGINT NOT NULL,
      started_at BIGINT,
      completed_at BIGINT,
      PRIMARY KEY (job_id, file_id)
  );

  CREATE INDEX ix_embedding_job_files_status
  ON embedding_job_files (job_id, status);

  This replaces a JSON failed-file list with queryable per-file state.

  ### Existing document_chunk

  Keep document_chunk as the 1536-dimensional physical vector table and add:

  ALTER TABLE document_chunk
      ADD COLUMN admin_id TEXT,
      ADD COLUMN embedding_model_id TEXT,
      ADD COLUMN file_id TEXT,
      ADD COLUMN knowledge_id TEXT,
      ADD COLUMN rag_chunk_id TEXT,
      ADD COLUMN modality VARCHAR(16),
      ADD COLUMN embedding_status VARCHAR(16),
      ADD COLUMN provenance_status VARCHAR(20)
          NOT NULL DEFAULT 'unattributed',
      ADD COLUMN created_at BIGINT,
      ADD COLUMN updated_at BIGINT;

  Foreign keys:

  - admin_id → user.id ON DELETE SET NULL
  - embedding_model_id → embedding_models.id ON DELETE RESTRICT
  - file_id → file.id ON DELETE SET NULL
  - knowledge_id → knowledge.id ON DELETE SET NULL
  - rag_chunk_id → rag_chunks.id ON DELETE CASCADE

  Indexes:

  CREATE UNIQUE INDEX ux_document_chunk_model_chunk_collection
  ON document_chunk (
      admin_id,
      embedding_model_id,
      rag_chunk_id,
      collection_name
  )
  WHERE rag_chunk_id IS NOT NULL;

  CREATE INDEX ix_document_chunk_admin_model_collection
  ON document_chunk (
      admin_id,
      embedding_model_id,
      collection_name,
      embedding_status
  )
  WHERE provenance_status = 'attributed';

  CREATE INDEX ix_document_chunk_file_id
  ON document_chunk (file_id);

  CREATE INDEX ix_document_chunk_knowledge_id
  ON document_chunk (knowledge_id);

  Preserve the existing IVFFlat vector and collection_name indexes. Phase 1 does not remove zero-padding or change reads/writes.

  ## Migration and Backfill

  1. Add an expand-only Alembic revision after b2c3d4e5f6a7.
      - Require PostgreSQL for vector DDL.
      - Ensure the vector extension exists.
      - Verify an existing document_chunk.vector is exactly vector(1536).
      - Create document_chunk through Alembic on a fresh database.
      - Remove dynamic table/index creation from the pgvector client.
      - Require PGVECTOR_DB_URL to be unset or equal to DATABASE_URL.

  2. Reconcile config data.
      - Confirm exactly one active config row per admin email/version.
      - Seed the global rag.embedding_model if missing.
      - For each user.role='admin', create a config row if missing.
      - Preserve a nonempty rag.embedding_model_user only if it resolves uniquely to an enabled registry row.
      - Otherwise snapshot the global default into rag.embedding_model_user.
      - Do not change API keys or unrelated JSON keys.

  3. Backfill resource ownership using RBAC-group-first precedence.
      - Resolve group owners with group.user_id; never use created_by as the identifier.
      - For knowledge bases, combine read/write group IDs from access_control. All referenced groups must resolve to the same
        admin.

      - With no assigned group, use an admin knowledge owner, then the owner’s single group admin.
      - For chat files, inspect chat.chat.history.messages[*].files and resolve chat.group_id.
      - For remaining files, use knowledge membership, then chat ownership, then an admin uploader or the uploader’s single
        group admin.

      - Multiple candidate admins are exceptions; never select the first group.

  4. Backfill vector provenance.
      - Read file_id from vmetadata.file_id and verify the file exists.
      - Set knowledge_id when collection_name equals an existing knowledge ID.
      - Use file attribution for file-<file_id> collections.
      - Set the seeded registry ID, modality='text', embedding_status='active', and provenance_status='attributed'.
      - Mark transient/out-of-scope collections out_of_scope.
      - Leave ambiguous rows unattributed.
      - Keep rag_chunk_id=NULL for legacy vectors because stable legacy chunk indexes cannot be reconstructed safely.

  The backfill must support dry-run and idempotent batched apply modes.

  ## Validation

  - Every admin has a nonempty config.data.rag.embedding_model_user.
  - Every stored admin model name resolves to exactly one enabled registry row.
  - Every owned group resolves through group.user_id to that admin’s config.
  - Changing the global default does not alter existing admin config rows.
  - New/promoted admins receive a snapshot of the current default.
  - Existing vector count equals attributed, out-of-scope, and unresolved counts.
  - No in-scope vector is assigned through email matching or first-group ordering.
  - Existing RAG reads, writes, collection counts, vector values, and indexes remain unchanged.

  No tests will be added or run without separate explicit permission. Any authorized validation must run inside Docker using
  only docker-compose.local.yaml.

  ## Assumptions

  - config.data.rag.embedding_model_user remains the permanent canonical admin selection.
  - The global config.data.rag.embedding_model becomes the super-admin-controlled default.
  - Model registry validation is application-enforced because JSON cannot carry a foreign key.
  - Only the 1536-dimensional Portkey text model is approved in Phase 1.
  - Phase 1 adds no public endpoint, UI, provider adapter, reindex worker, or retrieval cutover.
