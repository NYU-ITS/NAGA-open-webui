"""Fence index publications by generation; preserve existing index lineages.

API and workers must be upgraded together with old workers drained before this
migration. Old writes without generation provenance are rejected by the database.
"""

from alembic import op
import sqlalchemy as sa

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("admin_embedding_model_state", "embedding_jobs", "embeddings_1536"):
        op.add_column(table, sa.Column("index_generation_id", sa.Text(), nullable=True))
    op.execute(
        """
        WITH RECURSIVE lineage AS (
            SELECT id, id AS generation, ARRAY[id] AS visited
            FROM embedding_jobs WHERE source_job_id IS NULL
            UNION ALL
            SELECT child.id, parent.generation, parent.visited || child.id
            FROM embedding_jobs child JOIN lineage parent ON child.source_job_id = parent.id
            WHERE NOT child.id = ANY(parent.visited)
        )
        UPDATE embedding_jobs job SET index_generation_id = lineage.generation
        FROM lineage WHERE job.id = lineage.id
    """
    )
    # Corrupt/missing ancestry gets a distinct, fenced identity, never a guess
    # about another operation's successfully indexed files.
    op.execute(
        "UPDATE embedding_jobs SET index_generation_id = id WHERE index_generation_id IS NULL"
    )
    op.execute(
        """
        UPDATE admin_embedding_model_state state
        SET index_generation_id = COALESCE(
            (SELECT job.index_generation_id FROM embedding_jobs job
             WHERE job.id = state.latest_embedding_job_id AND job.admin_id = state.admin_id),
            'baseline:' || state.admin_id)
    """
    )
    op.execute(
        """
        UPDATE embedding_job_files files
        SET file_snapshot = jsonb_set(files.file_snapshot::jsonb, '{index_generation_id}',
                                     to_jsonb(job.index_generation_id))
        FROM embedding_jobs job WHERE files.job_id = job.id
    """
    )
    op.execute(
        """
        UPDATE embeddings_1536 vector SET index_generation_id = job.index_generation_id
        FROM embedding_jobs job WHERE vector.embedding_job_id = job.id
          AND vector.admin_id = job.admin_id
    """
    )
    op.execute(
        """
        UPDATE embeddings_1536 vector SET index_generation_id = state.index_generation_id
        FROM admin_embedding_model_state state
        WHERE vector.admin_id = state.admin_id AND vector.embedding_job_id IS NULL
          AND vector.embedding_model_id = state.active_embedding_model_id
          AND state.target_embedding_model_id IS NULL AND vector.embedding_status = 'active'
    """
    )
    for table in ("admin_embedding_model_state", "embedding_jobs"):
        op.alter_column(table, "index_generation_id", nullable=False)
    op.create_index(
        "ix_embeddings_generation",
        "embeddings_1536",
        ["admin_id", "index_generation_id", "file_id"],
    )
    op.create_index(
        "ix_jobs_generation", "embedding_jobs", ["admin_id", "index_generation_id"]
    )
    # Refuse late inserts/updates from pre-generation workers. Stale/inactive
    # invalidation remains available to normal model-change operations.
    op.execute(
        """
        CREATE FUNCTION guard_index_generation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.admin_id IS NOT NULL AND
                   current_setting('naga.index_writer_version', true) IS DISTINCT FROM '2' THEN
                    RAISE EXCEPTION 'generation-aware index worker required';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.admin_id IS NOT NULL AND
               current_setting('naga.index_writer_version', true) IS DISTINCT FROM '2' THEN
                RAISE EXCEPTION 'generation-aware index worker required';
            END IF;
            IF NEW.admin_id IS NOT NULL AND NEW.embedding_status IN ('active', 'building') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM admin_embedding_model_state state
                    WHERE state.admin_id = NEW.admin_id
                      AND state.index_generation_id = NEW.index_generation_id
                      AND COALESCE(state.target_embedding_model_id, state.active_embedding_model_id)
                          = NEW.embedding_model_id
                ) THEN
                    RAISE EXCEPTION 'stale index generation';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_index_generation BEFORE INSERT OR UPDATE OR DELETE ON embeddings_1536
        FOR EACH ROW EXECUTE FUNCTION guard_index_generation();
    """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER guard_index_generation ON embeddings_1536")
    op.execute("DROP FUNCTION guard_index_generation()")
    op.drop_index("ix_jobs_generation", table_name="embedding_jobs")
    op.drop_index("ix_embeddings_generation", table_name="embeddings_1536")
    for table in ("embeddings_1536", "embedding_jobs", "admin_embedding_model_state"):
        op.drop_column(table, "index_generation_id")
