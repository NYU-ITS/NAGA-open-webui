"""Prepare indexing settings and their durable jobs in the same transaction."""

from open_webui.config import Config
from open_webui.models.users import User
from open_webui.models.embeddings import AdminEmbeddingModelState, EmbeddingJob
from open_webui.retrieval.embedding.model_change import request_model_change, ModelChangeResult
from open_webui.retrieval.embedding.preparation import build_preparation_recipe


def stage_embedding_settings(config, form, email):
    if form.embedding_engine in {"openai", "portkey"}:
        if not form.embedding_model.strip():
            raise ValueError("An embedding model is required.")
        if form.openai_config is None or not form.openai_config.key.strip():
            raise ValueError("An embedding API key is required.")
    config.RAG_EMBEDDING_ENGINE = form.embedding_engine
    config.RAG_EMBEDDING_BATCH_SIZE = form.embedding_batch_size
    if form.openai_config is not None:
        config.RAG_OPENAI_API_BASE_URL = form.openai_config.url
        config.RAG_OPENAI_API_KEY.set(email, form.openai_config.key)
    if form.ollama_config is not None:
        config.RAG_OLLAMA_BASE_URL = form.ollama_config.url
        config.RAG_OLLAMA_API_KEY = form.ollama_config.key
    if form.reliability is not None:
        config.RAG_EMBEDDING_MAX_ATTEMPTS = form.reliability.max_attempts
        config.RAG_EMBEDDING_CONNECTION_TIMEOUT = form.reliability.connection_timeout_seconds
        config.RAG_EMBEDDING_READ_TIMEOUT = form.reliability.read_timeout_seconds


def prepare_settings_jobs(db, previous, proposed, user, *, embedding=None, force_reindex=False):
    """Reindex each configured admin whose recipe changes, or the caller's model.

    Global video/extraction settings affect every admin; scoped chunk settings
    affect only their owner. All inventories must succeed before any settings
    or jobs commit. Stable admin ordering avoids competing multi-admin locks.
    """
    jobs = []
    for admin in db.query(User).filter_by(role="admin").order_by(User.id).all():
        old_recipe = build_preparation_recipe(previous, admin.email)
        new_recipe = build_preparation_recipe(proposed, admin.email)
        recipe_changed = old_recipe.sha256 != new_recipe.sha256
        own_update = admin.id == user.id and embedding is not None
        force = recipe_changed or (admin.id == user.id and force_reindex)
        if not force and not own_update:
            continue
        model = embedding.embedding_model if own_update else proposed.RAG_EMBEDDING_MODEL_USER.get(admin.email)
        if not model:
            if own_update or force_reindex and admin.id == user.id:
                raise ValueError("Select an embedding model before requesting indexing.")
            continue  # An unconfigured admin has no index to rebuild.
        result, _ = request_model_change(
            admin_id=admin.id,
            target_model_id=model,
            authenticated_user_id=user.id,
            config=proposed,
            force_reindex=force,
            db=db,
            global_settings_change=recipe_changed,
        )
        if isinstance(result, ModelChangeResult):
            # Keep the supported reindex_model_change type assigned by the
            # model-change workflow, including same-model recipe rebuilds.
            jobs.append(result)
    if jobs:
        proposed.set_value(user.email, "rag.settings_indexing_jobs", [job.job_id for job in jobs])
    return jobs


def settings_indexing_status(db, user):
    """Expose the caller's last settings operation and their own latest index."""
    row = db.query(Config).filter_by(email=user.email, version=0).first()
    data = row.data if row and isinstance(row.data, dict) else {}
    job_ids = list(data.get("rag", {}).get("settings_indexing_jobs", []))
    state = db.query(AdminEmbeddingModelState).filter_by(admin_id=user.id).first()
    if state and state.latest_embedding_job_id not in job_ids:
        job_ids.append(state.latest_embedding_job_id)
    jobs = []
    seen = set()
    for job in db.query(EmbeddingJob).filter(EmbeddingJob.id.in_(job_ids)).all():
        if job.admin_id != user.id and job.created_by_user_id != user.id:
            continue
        # A retry or replacement supersedes the stored operation's job. Follow
        # durable admin state so a recovered operation does not stay "failed".
        current = db.query(AdminEmbeddingModelState).filter_by(admin_id=job.admin_id).first()
        if current and current.latest_embedding_job_id:
            latest = db.query(EmbeddingJob).filter_by(id=current.latest_embedding_job_id).first()
            if latest is not None:
                job = latest
        if job.id in seen:
            continue
        seen.add(job.id)
        jobs.append({
            "job_id": job.id,
            "status": job.status,
            "total_files": job.total_files,
            "processed_files": job.processed_files,
            "failed_files": job.failed_files,
            "incompatible_files": job.incompatible_files,
            "error_code": job.error_code,
            "own_index": job.admin_id == user.id,
            "can_retry": job.admin_id == user.id and job.status in {"failed", "partially_failed"},
        })
    statuses = {job["status"] for job in jobs}
    if statuses & {"failed", "partially_failed"}:
        status = "failed"
    elif statuses & {"queued", "processing"}:
        status = "pending"
    elif jobs:
        status = "ready"
    else:
        status = "not_required"
    return {"status": status, "jobs": jobs, "in_progress": bool(statuses & {"queued", "processing"})}
