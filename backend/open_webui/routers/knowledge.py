from io import BytesIO
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request, UploadFile, File
import logging

from open_webui.models.knowledge import (
    Knowledge,
    Knowledges,
    KnowledgeForm,
    KnowledgeModel,
    KnowledgeResponse,
    KnowledgeUserResponse,
)
from open_webui.internal.db import get_db
from open_webui.retrieval.embedding.knowledge_status import (
    KnowledgeIndexingStatusResponse,
    KnowledgeIndexingStatusSummary,
    build_knowledge_indexing_statuses,
)
from open_webui.models.files import Files, FileModel, FileModelResponse
from open_webui.routers.retrieval import (
    process_file,
    ProcessFileForm,
    process_files_batch,
    BatchProcessFilesForm,
    BatchProcessFilesResult,
)
from open_webui.utils.job_queue import is_job_queue_available
from open_webui.storage.provider import Storage
from open_webui.routers.audio import transcribe
from open_webui.utils.file_cleanup import (
    cleanup_knowledge_collection,
    cleanup_file_from_knowledge_only,
)

from open_webui.constants import ERROR_MESSAGES
from open_webui.utils.auth import get_verified_user
from open_webui.utils.access_control import has_access, has_permission
from open_webui.utils.super_admin import is_super_admin


from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.models import Models, ModelForm

# OpenTelemetry instrumentation (conditional import)
try:
    from open_webui.utils.otel_instrumentation import (
        trace_span_async,
        add_span_event,
        set_span_attribute,
    )
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    # Create no-op functions if OTEL not available
    # NOTE: Must be regular function (not async def) to match @asynccontextmanager signature
    def trace_span_async(*args, **kwargs):
        span_name = kwargs.get('name', args[0] if args else 'unknown')
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _noop():
            # Get logger at call time (log variable will be defined by then)
            _log = logging.getLogger(__name__)
            try:
                _log.debug(f"[trace_span_async] Generator entering (OTEL unavailable, no-op) for span '{span_name}'")
                yield None
                _log.debug(f"[trace_span_async] Generator exiting normally (OTEL unavailable, no-op) for span '{span_name}'")
            except GeneratorExit as ge:
                _log.debug(f"[trace_span_async] GeneratorExit caught (OTEL unavailable, no-op) for span '{span_name}': {ge}")
                # Properly handle generator exit
                raise
            except Exception as e:
                _log.warning(f"[trace_span_async] Exception thrown into generator (OTEL unavailable, no-op) for span '{span_name}': {type(e).__name__}: {e}", exc_info=True)
                # Properly handle exceptions thrown into generator - must re-raise or return
                # Re-raising ensures the exception propagates correctly
                raise
        return _noop()
    def add_span_event(*args, **kwargs):
        pass
    def set_span_attribute(*args, **kwargs):
        pass

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

# Safe wrapper functions that NEVER fail - OTEL is monitoring only, must not affect task execution
def safe_add_span_event(event_name, attributes=None):
    """Safely add span event - never fails, even if OTEL is broken"""
    try:
        add_span_event(event_name, attributes)
    except Exception as e:
        log.debug(f"OTEL add_span_event failed (non-critical): {e}")

def safe_set_span_attribute(span, key, value):
    """Safely set span attribute - never fails, even if OTEL is broken"""
    try:
        if span:
            set_span_attribute(span, key, value)
    except Exception as e:
        log.debug(f"OTEL set_span_attribute failed (non-critical): {e}")

def safe_trace_span_async(*args, **kwargs):
    """Safely create async trace span - never fails, even if OTEL is broken
    
    Returns an async context manager (same signature as trace_span_async).
    Can be used with: async with safe_trace_span_async(...) as span:
    """
    span_name = kwargs.get('name', args[0] if args else 'unknown')
    try:
        log.debug(f"[safe_trace_span_async] Attempting to create span '{span_name}'")
        return trace_span_async(*args, **kwargs)  # Returns async context manager, not a coroutine
    except Exception as e:
        log.warning(f"[safe_trace_span_async] OTEL trace_span_async failed (non-critical) for span '{span_name}': {type(e).__name__}: {e}", exc_info=True)
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _noop():
            try:
                log.debug(f"[safe_trace_span_async] Generator entering (safe fallback) for span '{span_name}'")
                yield None
                log.debug(f"[safe_trace_span_async] Generator exiting normally (safe fallback) for span '{span_name}'")
            except GeneratorExit as ge:
                log.debug(f"[safe_trace_span_async] GeneratorExit caught (safe fallback) for span '{span_name}': {ge}")
                # Properly handle generator exit
                raise
            except Exception as gen_exc:
                log.warning(f"[safe_trace_span_async] Exception thrown into generator (safe fallback) for span '{span_name}': {type(gen_exc).__name__}: {gen_exc}", exc_info=True)
                # Properly handle exceptions thrown into generator - must re-raise or return
                # Re-raising ensures the exception propagates correctly
                raise
        return _noop()

router = APIRouter()

############################
# getKnowledgeBases
############################


@router.get("/", response_model=list[KnowledgeUserResponse])
async def get_knowledge(user=Depends(get_verified_user)):
    knowledge_bases = []

    # if user.role == "admin":
    #     knowledge_bases = Knowledges.get_knowledge_bases()
    # else:
    knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(user.id, "read")

    # Batch file operations: Collect all file_ids from all knowledge bases first
    all_file_ids = []
    knowledge_file_ids_map = {}  # Maps knowledge_base.id -> list of file_ids
    
    for knowledge_base in knowledge_bases:
        file_ids = []
        if knowledge_base.data:
            file_ids = knowledge_base.data.get("file_ids", [])
        
        if file_ids:
            all_file_ids.extend(file_ids)
            knowledge_file_ids_map[knowledge_base.id] = file_ids
        else:
            knowledge_file_ids_map[knowledge_base.id] = []

    # Single batch query for all file metadata
    all_files_dict = {}
    if all_file_ids:
        all_files = Files.get_file_metadatas_by_ids(all_file_ids)
        all_files_dict = {file.id: file for file in all_files}

    # Build response with files mapped back to knowledge bases
    knowledge_with_files = []
    knowledge_bases_to_update = []  # Track knowledge bases with missing files
    
    for knowledge_base in knowledge_bases:
        file_ids = knowledge_file_ids_map.get(knowledge_base.id, [])
        files = []
        
        if file_ids:
            # Get files from the batch-loaded dictionary
            files = [all_files_dict[file_id] for file_id in file_ids if file_id in all_files_dict]
            
            # Check if all files exist
            if len(files) != len(file_ids):
                missing_files = list(set(file_ids) - set([file.id for file in files]))
                if missing_files:
                    # Track for batch update
                    knowledge_bases_to_update.append({
                        "knowledge_base": knowledge_base,
                        "missing_files": missing_files,
                        "file_ids": file_ids
                    })

        knowledge_with_files.append(
            KnowledgeUserResponse(
                **knowledge_base.model_dump(),
                files=files,
            )
        )
    
    # Batch update knowledge bases with missing files removed
    for kb_update in knowledge_bases_to_update:
        file_ids = [fid for fid in kb_update["file_ids"] if fid not in kb_update["missing_files"]]
        Knowledges.remove_files_from_knowledge_by_id(
            id=kb_update["knowledge_base"].id,
            file_ids=kb_update["missing_files"],
        )
        
        # Update the response with corrected files
        for kb_response in knowledge_with_files:
            if kb_response.id == kb_update["knowledge_base"].id:
                kb_response.files = [all_files_dict[fid] for fid in file_ids if fid in all_files_dict]
                break

    return knowledge_with_files


@router.get("/list", response_model=list[KnowledgeUserResponse])
async def get_knowledge_list(user=Depends(get_verified_user)):
    knowledge_bases = []

    # if user.role == "admin":
    #     knowledge_bases = Knowledges.get_knowledge_bases()
    # else:
    knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(user.id, "write")

    # Batch file operations: Collect all file_ids from all knowledge bases first
    all_file_ids = []
    knowledge_file_ids_map = {}  # Maps knowledge_base.id -> list of file_ids
    
    for knowledge_base in knowledge_bases:
        file_ids = []
        if knowledge_base.data:
            file_ids = knowledge_base.data.get("file_ids", [])
        
        if file_ids:
            all_file_ids.extend(file_ids)
            knowledge_file_ids_map[knowledge_base.id] = file_ids
        else:
            knowledge_file_ids_map[knowledge_base.id] = []

    # Single batch query for all file metadata
    all_files_dict = {}
    if all_file_ids:
        all_files = Files.get_file_metadatas_by_ids(all_file_ids)
        all_files_dict = {file.id: file for file in all_files}

    # Build response with files mapped back to knowledge bases
    knowledge_with_files = []
    knowledge_bases_to_update = []  # Track knowledge bases with missing files
    
    for knowledge_base in knowledge_bases:
        file_ids = knowledge_file_ids_map.get(knowledge_base.id, [])
        files = []
        
        if file_ids:
            # Get files from the batch-loaded dictionary
            files = [all_files_dict[file_id] for file_id in file_ids if file_id in all_files_dict]
            
            # Check if all files exist
            if len(files) != len(file_ids):
                missing_files = list(set(file_ids) - set([file.id for file in files]))
                if missing_files:
                    # Track for batch update
                    knowledge_bases_to_update.append({
                        "knowledge_base": knowledge_base,
                        "missing_files": missing_files,
                        "file_ids": file_ids
                    })

        knowledge_with_files.append(
            KnowledgeUserResponse(
                **knowledge_base.model_dump(),
                files=files,
            )
        )
    
    # Batch update knowledge bases with missing files removed
    for kb_update in knowledge_bases_to_update:
        file_ids = [fid for fid in kb_update["file_ids"] if fid not in kb_update["missing_files"]]
        Knowledges.remove_files_from_knowledge_by_id(
            id=kb_update["knowledge_base"].id,
            file_ids=kb_update["missing_files"],
        )
        
        # Update the response with corrected files
        for kb_response in knowledge_with_files:
            if kb_response.id == kb_update["knowledge_base"].id:
                kb_response.files = [all_files_dict[fid] for fid in file_ids if fid in all_files_dict]
                break

    return knowledge_with_files


############################
# GetKnowledgeIndexingStatus
############################


def _can_edit_knowledge(user, knowledge: Knowledge) -> bool:
    """Mirror the authorization used by knowledge mutation endpoints."""
    if user.role == "admin" or knowledge.user_id == user.id:
        return True
    if not isinstance(knowledge.access_control, dict):
        return False
    write_access = knowledge.access_control.get("write")
    if not isinstance(write_access, dict):
        return False
    if not isinstance(write_access.get("group_ids", []), list):
        return False
    if not isinstance(write_access.get("user_ids", []), list):
        return False
    return has_access(user.id, "write", knowledge.access_control)


@router.get(
    "/indexing/status",
    response_model=list[KnowledgeIndexingStatusSummary],
)
def get_knowledge_indexing_statuses(user=Depends(get_verified_user)):
    """Return reindex summaries for knowledge bases the viewer may edit."""
    with get_db() as db:
        knowledge_rows = (
            db.query(Knowledge).order_by(Knowledge.updated_at.desc()).all()
        )
        editable_rows = [
            knowledge
            for knowledge in knowledge_rows
            if _can_edit_knowledge(user, knowledge)
        ]
        return build_knowledge_indexing_statuses(
            db,
            editable_rows,
            viewer_id=user.id,
            viewer_role=user.role,
            include_failure_details=False,
        )


@router.get(
    "/{id}/indexing/status",
    response_model=KnowledgeIndexingStatusResponse,
)
def get_knowledge_indexing_status(id: str, user=Depends(get_verified_user)):
    """Return detailed reindex status for one editable knowledge base."""
    with get_db() as db:
        knowledge = db.query(Knowledge).filter(Knowledge.id == id).first()
        if knowledge is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge not found.",
            )
        if not _can_edit_knowledge(user, knowledge):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Write access is required to view indexing status.",
            )

        statuses = build_knowledge_indexing_statuses(
            db,
            [knowledge],
            viewer_id=user.id,
            viewer_role=user.role,
            include_failure_details=True,
        )
        return statuses[0]


############################
# CreateNewKnowledge
############################


@router.post("/create", response_model=Optional[KnowledgeResponse])
async def create_new_knowledge(
    request: Request, form_data: KnowledgeForm, user=Depends(get_verified_user)
):
    if user.role != "admin" and not has_permission(
        user.id, "workspace.knowledge", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    creator_user_id = user.id
    if is_super_admin(user):
        assign_to = form_data.model_dump().get('assign_to_email')
        if assign_to:
            from open_webui.models.users import Users
            target_user = Users.get_user_by_email(assign_to)
            if target_user:
                creator_user_id = target_user.id
    
    knowledge = Knowledges.insert_new_knowledge(creator_user_id, form_data)

    if knowledge:
        return knowledge
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FILE_EXISTS,
        )


############################
# GetKnowledgeById
############################


class KnowledgeFilesWarning(BaseModel):
    code: Literal["file_processing_partial_failure"]
    message: str


class KnowledgeFilesResponse(KnowledgeModel):
    files: list[FileModelResponse]
    warnings: list[KnowledgeFilesWarning] = Field(default_factory=list)
    failures: list[BatchProcessFilesResult] = Field(default_factory=list)


# @router.get("/{id}", response_model=Optional[KnowledgeFilesResponse])
# async def get_knowledge_by_id(id: str, user=Depends(get_verified_user)):
#     knowledge = Knowledges.get_knowledge_by_id(id=id)

#     if knowledge:

#         if (
#             user.role == "admin"
#             or knowledge.user_id == user.id
#             or has_access(user.id, "read", knowledge.access_control)
#         ):

#             file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
#             files = Files.get_files_by_ids(file_ids)

#             return KnowledgeFilesResponse(
#                 **knowledge.model_dump(),
#                 files=files,
#             )
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail=ERROR_MESSAGES.NOT_FOUND,
#         )


@router.get("/{id}", response_model=Optional[KnowledgeFilesResponse])
async def get_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    from open_webui.utils.workspace_access import item_assigned_to_user_groups
    
    knowledge = Knowledges.get_knowledge_by_id(id=id)

    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge not found")

    if (
        knowledge.user_id == user.id
        or has_access(user.id, "read", knowledge.access_control)
        or item_assigned_to_user_groups(user.id, knowledge, "read")
    ):

        file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
        files = Files.get_files_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateKnowledgeById
############################


@router.post("/{id}/update", response_model=Optional[KnowledgeFilesResponse])
async def update_knowledge_by_id(
    id: str,
    form_data: KnowledgeForm,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    # Is the user the original creator, in a group with write access, or an admin
    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if is_super_admin(user):
        assign_to = form_data.model_dump().get('assign_to_email')
        if assign_to:
            from open_webui.models.users import Users
            target_user = Users.get_user_by_email(assign_to)
            if target_user:
                knowledge = Knowledges.update_knowledge_by_id(id=id, form_data=form_data)
                if knowledge:
                    from open_webui.internal.db import get_db
                    from open_webui.models.knowledge import Knowledge
                    with get_db() as db:
                        db.query(Knowledge).filter_by(id=id).update({"user_id": target_user.id})
                        db.commit()
                    knowledge = Knowledges.get_knowledge_by_id(id=id)
                    file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
                    files = Files.get_files_by_ids(file_ids)
                    return KnowledgeFilesResponse(**knowledge.model_dump(), files=files)

    knowledge = Knowledges.update_knowledge_by_id(id=id, form_data=form_data)
    if knowledge:
        file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
        files = Files.get_files_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ID_TAKEN,
        )


############################
# AddFileToKnowledge
############################


class KnowledgeFileIdForm(BaseModel):
    file_id: str


@router.post("/{id}/file/add", response_model=Optional[KnowledgeFilesResponse])
async def add_file_to_knowledge_by_id(
    request: Request,
    id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
    file_metadata: dict = {},
):
    import os
    import uuid
    from open_webui.models.files import FileForm

    knowledge = Knowledges.get_knowledge_by_id(id=id)

    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"file.content_type: {file.content_type}")
    
    # Generate file_id early for instrumentation
    unsanitized_filename = file.filename
    filename = os.path.basename(unsanitized_filename)
    file_id = str(uuid.uuid4())
    name = filename

    from open_webui.retrieval.embedding.errors import (
        EMBEDDING_IMAGE_FORMAT_UNSUPPORTED,
        FILE_PROCESSING_FAILED,
        EmbeddingError,
        safe_file_processing_error_message,
    )
    from open_webui.retrieval.embedding.preparation import (
        UploadByteLimitExceededError,
        canonical_upload_content_type,
        read_upload_bytes,
    )

    try:
        max_size_mb = request.app.state.config.FILE_MAX_SIZE
    except (AttributeError, KeyError):
        max_size_mb = None
    try:
        upload_bytes = read_upload_bytes(file, max_size_mb)
    except UploadByteLimitExceededError as error:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=ERROR_MESSAGES.FILE_TOO_LARGE(size=f"{error.max_size_mb}MB"),
        ) from None
    try:
        upload_content_type = canonical_upload_content_type(
            upload_bytes,
            filename,
            file.content_type,
        )
    except EmbeddingError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
                if error.code == EMBEDDING_IMAGE_FORMAT_UNSUPPORTED
                else status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code": error.code,
                "message": safe_file_processing_error_message(error.code),
            },
        )
    
    # Create OTEL span for file upload
    # CRITICAL: Use safe_trace_span_async to ensure OTEL failures never prevent file uploads
    async with safe_trace_span_async(
        name="file.upload",
        attributes={
            "file.id": file_id,
            "file.name": name,
            "file.content_type": upload_content_type,
            "knowledge.id": id,
            "user.id": str(user.id) if user else None,
        },
    ) as span:
        try:
            safe_add_span_event("file.upload.started", {"file_id": file_id, "filename": name})
            
            filename = f"{file_id}_{filename}"
            contents, file_path = Storage.upload_file(
                BytesIO(upload_bytes), filename
            )
            
            # Update span with file size after upload
            safe_set_span_attribute(span, "file.size", len(contents))
            
            safe_add_span_event("file.upload.stored", {"file_size": len(contents)})

            file_item = Files.insert_new_file(
                user.id,
                FileForm(
                    **{
                        "id": file_id,
                        "filename": name,
                        "path": file_path,
                        "meta": {
                            "name": name,
                            "content_type": upload_content_type,
                            "size": len(contents),
                            "data": file_metadata,
                            "processing_error_code": None,
                            "processing_warnings": [],
                            "visual_summary": {
                                "figure_count": 0,
                                "table_image_count": 0,
                                "image_chunk_count": 0,
                                "text_chunk_count": 0,
                            },
                        },
                    }
                ),
            )

            if file_item is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Error uploading file"),
                )

            # Persist membership before dispatch. RQ can start immediately, so
            # the processing worker must never rely on a membership that the
            # request intends to write only after enqueueing.
            updated_knowledge = Knowledges.add_files_to_knowledge_by_id(
                id=id,
                file_ids=[file_id],
            )
            if updated_knowledge is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update knowledge base metadata.",
                )

            # Process file in background
            # Use job queue if available (distributed processing), otherwise use BackgroundTasks
            job_id = None
            if background_tasks or is_job_queue_available():
                try:
                    if upload_content_type in [
                        "audio/mpeg",
                        "audio/wav",
                        "audio/ogg",
                        "audio/x-m4a",
                    ]:
                        # For audio files, transcribe first (this is quick), then process in background
                        file_path_for_transcribe = Storage.get_file(file_path)
                        result = transcribe(request, file_path_for_transcribe, user)
                        # Note: process_file may return job_id if using job queue
                        process_file(
                            request,
                            ProcessFileForm(file_id=file_id, content=result.get("text", "")),
                            user=user,
                            knowledge_id=id,  # Pass knowledge_id for single embedding
                            background_tasks=background_tasks,
                        )
                    else:
                        # Process the file for both file and knowledge collections in background
                        # process_file will use job queue if available, otherwise BackgroundTasks
                        process_file(
                            request,
                            ProcessFileForm(file_id=file_id),
                            user=user,
                            knowledge_id=id,  # Pass knowledge_id for single embedding
                            background_tasks=background_tasks,
                        )
                    safe_add_span_event("file.upload.queued", {"file_id": file_id})
                except Exception as e:
                    log.error(
                        "Background processing dispatch failed for file %s (%s)",
                        file_id,
                        type(e).__name__,
                    )
                    log.error(f"Error starting background processing for file: {file_id}")
                    safe_add_span_event("file.upload.queue_failed", {
                        "file_id": file_id,
                        "error_type": type(e).__name__,
                    })
                    # Mark file as error since background task failed to start
                    try:
                        Files.update_file_metadata_by_id(
                            file_id,
                            {
                                "processing_status": "error",
                                "processing_error_code": FILE_PROCESSING_FAILED,
                                "processing_error": safe_file_processing_error_message(
                                    FILE_PROCESSING_FAILED
                                ),
                            },
                        )
                    except Exception as update_error:
                        log.exception(f"Failed to update file status after background task error: {update_error}")
                    # Continue anyway - file is uploaded, user can retry processing manually
            
            updated_knowledge = Knowledges.get_knowledge_by_id(id=id)
            if updated_knowledge is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
            files = Files.get_files_by_ids(
                (updated_knowledge.data or {}).get("file_ids", [])
            )
            safe_add_span_event(
                "file.upload.completed",
                {"file_id": file_id, "knowledge_id": id},
            )
            return KnowledgeFilesResponse(
                **updated_knowledge.model_dump(),
                files=files,
            )

        except HTTPException:
            raise
        except Exception as e:
            log.error("Knowledge file upload failed (%s)", type(e).__name__)
            safe_add_span_event("file.upload.error", {
                "error.type": type(e).__name__,
            })
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error uploading file"),
            )


@router.post("/{id}/file/update", response_model=Optional[KnowledgeFilesResponse])
def update_file_from_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    data = knowledge.data if isinstance(knowledge.data, dict) else {}
    file_ids = data.get("file_ids", [])
    if not isinstance(file_ids, list) or form_data.file_id not in file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("File is not in this knowledge collection"),
        )

    # Reconcile the existing projection in the background. The model-aware
    # ingestion transaction replaces current rows only after preparation and
    # every embedding succeed, so do not pre-delete the active projection.
    # Use job queue if available (distributed processing), otherwise use BackgroundTasks or synchronous
    if background_tasks or is_job_queue_available():
        # Process in background (uses job queue if available)
        process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
            knowledge_id=id,
            background_tasks=background_tasks,
        )
    else:
        # Process synchronously (backward compatibility - only if job queue and background_tasks unavailable)
        # Note: This code path should not be reached since background_tasks is always injected by FastAPI
        # But if somehow we get here, we'll just skip processing with a warning
        log.warning(
            f"Cannot process file {form_data.file_id} synchronously - "
            "background_tasks not available and job queue not available. "
            "File processing will need to be triggered manually."
        )

    if knowledge:
        files = Files.get_files_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# RemoveFileFromKnowledge
############################


@router.post("/{id}/file/remove", response_model=Optional[KnowledgeFilesResponse])
def remove_file_from_knowledge_by_id(
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    """
    Remove a file from a knowledge collection.

    This removes only the membership and its knowledge projection. The file
    itself remains available until explicitly deleted through the file endpoint.
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    log.info(
        f"Removing file {form_data.file_id} from knowledge collection {id} "
        f"by user {user.id} (email: {user.email})"
    )

    # Check if file is actually in the current knowledge base
    data = knowledge.data or {}
    file_ids = data.get("file_ids", [])
    if not isinstance(file_ids, list) or form_data.file_id not in file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("File is not in this knowledge collection"),
        )

    # Always remove only this membership. File lifecycle is independent of KB
    # membership; an explicit file delete owns full cleanup. This avoids an
    # unlocked last-reference decision racing a simultaneous add/remove.
    success, details = cleanup_file_from_knowledge_only(form_data.file_id, id)
    if not success:
        log.error(
            "Failed to remove file %s from knowledge collection %s",
            form_data.file_id,
            id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(
                "Error removing file from knowledge collection"
            ),
        )

    # Refresh knowledge base to get updated file list
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error retrieving updated knowledge base"),
        )

    # Get updated file list
    data = knowledge.data or {}
    file_ids = data.get("file_ids", [])
    files = Files.get_files_by_ids(file_ids) if file_ids else []

    log.info(
        f"Successfully removed file {form_data.file_id} from knowledge collection {id}. "
        f"Remaining files: {len(files)}"
    )

    return KnowledgeFilesResponse(
        **knowledge.model_dump(),
        files=files,
    )


############################
# DeleteKnowledgeById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"Deleting knowledge base: {id} (name: {knowledge.name})")

    # Get all models
    models = Models.get_all_models(user.id,user.email)
    log.info(f"Found {len(models)} models to check for knowledge base {id}")

    # Update models that reference this knowledge base
    for model in models:
        if model.meta and hasattr(model.meta, "knowledge"):
            knowledge_list = model.meta.knowledge or []
            # Filter out the deleted knowledge base
            updated_knowledge = [k for k in knowledge_list if k.get("id") != id]

            # If the knowledge list changed, update the model
            if len(updated_knowledge) != len(knowledge_list):
                log.info(f"Updating model {model.id} to remove knowledge base {id}")
                model.meta.knowledge = updated_knowledge
                # Create a ModelForm for the update
                model_form = ModelForm(
                    id=model.id,
                    name=model.name,
                    base_model_id=model.base_model_id,
                    meta=model.meta,
                    params=model.params,
                    access_control=model.access_control,
                    is_active=model.is_active,
                )
                Models.update_model_by_id(model.id, model_form)

    result = cleanup_knowledge_collection(id, delete_knowledge=True)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Knowledge base could not be deleted."),
        )
    return True


############################
# ResetKnowledgeById
############################


@router.post("/{id}/reset", response_model=Optional[KnowledgeResponse])
async def reset_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if not cleanup_knowledge_collection(id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Knowledge base could not be reset."),
        )
    knowledge = Knowledges.get_knowledge_by_id(id=id)

    return knowledge


############################
# AddFilesToKnowledge
############################


@router.post("/{id}/files/batch/add", response_model=Optional[KnowledgeFilesResponse])
def add_files_to_knowledge_batch(
    request: Request,
    id: str,
    form_data: list[KnowledgeFileIdForm],
    user=Depends(get_verified_user),
):
    """
    Add multiple files to a knowledge base
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Get files content
    log.info(f"files/batch/add - {len(form_data)} files")
    files: List[FileModel] = []
    for form in form_data:
        file = Files.get_file_by_id(form.file_id)
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {form.file_id} not found",
            )
        if user.role != "admin" and file.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        files.append(file)

    # Persist memberships before synchronous processing. The shared ingestion
    # path accepts only current knowledge memberships, which prevents orphaned
    # collection vectors if a request or worker races with metadata updates.
    knowledge = Knowledges.add_files_to_knowledge_by_id(
        id=id,
        file_ids=[file.id for file in files],
    )
    if knowledge is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Knowledge membership could not be updated."),
        )

    existing_file_ids = list((knowledge.data or {}).get("file_ids", []))

    # Process files
    try:
        result = process_files_batch(
            request=request,
            form_data=BatchProcessFilesForm(files=files, collection_name=id),
            user=user,
        )
    except Exception as error:
        log.error(
            "Knowledge batch processing failed | knowledge_id=%s | type=%s",
            id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Some files could not be processed."),
        )

    # If there were any errors, include them in the response
    if result.errors:
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=Files.get_files_by_ids(existing_file_ids),
            warnings=[
                KnowledgeFilesWarning(
                    code="file_processing_partial_failure",
                    message="Some files could not be processed.",
                )
            ],
            failures=result.errors,
        )

    return KnowledgeFilesResponse(
        **knowledge.model_dump(), files=Files.get_files_by_ids(existing_file_ids)
    )
