import logging
import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import time 
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.files import (
    FileForm,
    FileModelResponse,
    Files,
    sanitize_public_visual_summary,
)
from open_webui.models.knowledge import Knowledges
from open_webui.routers.retrieval import ProcessFileForm, process_file
from open_webui.utils.job_queue import is_job_queue_available
from open_webui.routers.audio import transcribe
from open_webui.storage.provider import Storage
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.file_cleanup import cleanup_file_completely
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


router = APIRouter()


def _can_read_file(user, file) -> bool:
    if file is None:
        return False
    if user.role == "admin" or file.user_id == user.id:
        return True
    return Knowledges.user_has_read_access_to_file(user.id, file.id)

############################
# Upload File
############################


@router.post("/", response_model=FileModelResponse)
def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
    file_metadata: dict = {},
):
    log.info(f"file.content_type: {file.content_type}")
    try:
        unsanitized_filename = file.filename
        filename = os.path.basename(unsanitized_filename)

        from open_webui.retrieval.embedding.errors import (
            EmbeddingError,
            FILE_PROCESSING_FAILED,
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
                detail=ERROR_MESSAGES.FILE_TOO_LARGE(
                    size=f"{error.max_size_mb}MB"
                ),
            ) from None

        upload_content_type = canonical_upload_content_type(
            upload_bytes,
            filename,
            file.content_type,
        )

        # Video preflight: validate with ffprobe before storage
        if upload_content_type in {"video/mp4", "video/mpeg"}:
            from open_webui.retrieval.embedding.preparation import validate_video
            from open_webui.retrieval.embedding.errors import (
                VIDEO_DURATION_EXCEEDED,
                VIDEO_VALIDATION_FAILED,
            )

            try:
                max_video_duration = getattr(
                    request.app.state.config, "RAG_VIDEO_MAX_DURATION", 120
                )
                if hasattr(max_video_duration, "value"):
                    max_video_duration = max_video_duration.value
                validate_video(
                    upload_bytes,
                    max_duration_seconds=int(max_video_duration),
                )
            except EmbeddingError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": error.code,
                        "message": safe_file_processing_error_message(error.code),
                    },
                ) from None

        # replace filename with uuid
        id = str(uuid.uuid4())
        name = filename
        filename = f"{id}_{filename}"
        contents, file_path = Storage.upload_file(
            BytesIO(upload_bytes), filename
        )

        file_item = Files.insert_new_file(
            user.id,
            FileForm(
                **{
                    "id": id,
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
                            "video_chunk_count": 0,
                        },
                    },
                }
            ),
        )

        # Process file in background
        # NOTE: process_file will set processing_status="pending" when it enqueues the job
        # We don't set it here to avoid race condition where process_file sees "pending" and skips processing
        # Use job queue if available (distributed processing), otherwise use BackgroundTasks
        if background_tasks or is_job_queue_available():
            try:
                if upload_content_type in [
                    "audio/mpeg",
                    "audio/wav",
                    "audio/ogg",
                    "audio/x-m4a",
                ]:
                    # For audio files, transcribe first (this is quick), then process in background
                    file_path = Storage.get_file(file_path)
                    result = transcribe(request, file_path, user)
                    process_file(
                        request,
                        ProcessFileForm(file_id=id, content=result.get("text", "")),
                        user=user,
                        background_tasks=background_tasks,
                    )
                else:
                    # Process in background (uses job queue if available)
                    process_file(
                        request,
                        ProcessFileForm(file_id=id),
                        user=user,
                        background_tasks=background_tasks,
                    )
            except Exception as e:
                log.error(
                    "Background processing dispatch failed for file %s (%s)",
                    id,
                    type(e).__name__,
                )
                log.error(f"Error starting background processing for file: {id}")
                # Mark file as error since background task failed to start
                try:
                    Files.update_file_metadata_by_id(
                        id,
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
        
        # Get file item to return
        file_item = Files.get_file_by_id(id=id)

        if file_item:
            return FileModelResponse.model_validate(file_item)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error uploading file"),
            )

    except EmbeddingError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
                if e.code == "embedding_image_format_unsupported"
                else status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code": e.code,
                "message": safe_file_processing_error_message(e.code),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("File upload failed (%s)", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error uploading file"),
        )




## download file with temporary link /start

@router.get("/download/{id}")
async def download_by_id(id: str, user=Depends(get_verified_user)):

    file = Files.get_file_by_id(id)
    # if not file:
    #     raise HTTPException(
    #         status_code=status.HTTP_404_NOT_FOUND,
    #         detail=ERROR_MESSAGES.NOT_FOUND,
    #     )

    # expiry = file.meta.get("download_expiry") if file.meta else None
    # if not expiry or time.time() > expiry:
    #     raise HTTPException(
    #         status_code=status.HTTP_410_GONE,
    #         detail=ERROR_MESSAGES.DEFAULT("Download link has expired. Download links are valid for 30 minutes."),
    #     )
        
    
    
    if _can_read_file(user, file):
        try:
            file_path = Storage.get_file(file.path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                # Handle Unicode filenames
                filename = file.meta.get("name", file.filename)
                encoded_filename = quote(filename)  # RFC5987 encoding

                content_type = file.meta.get("content_type")
                filename = file.meta.get("name", file.filename)
                encoded_filename = quote(filename)
                headers = {}

                if content_type == "application/pdf" or filename.lower().endswith(
                    ".pdf"
                ):
                    headers["Content-Disposition"] = (
                        f"inline; filename*=UTF-8''{encoded_filename}"
                    )
                    content_type = "application/pdf"
                elif content_type != "text/plain":
                    headers["Content-Disposition"] = (
                        f"attachment; filename*=UTF-8''{encoded_filename}"
                    )

                return FileResponse(file_path, headers=headers, media_type=content_type)

            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        except Exception as e:
            log.exception(e)
            log.error("Error downloading file content")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error downloading file content"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
## download file with temporary link /end




############################
# List Files
############################


@router.get("/", response_model=list[FileModelResponse])
async def list_files(user=Depends(get_verified_user)):
    if user.role == "admin":
        files = Files.get_files()
    else:
        files = Files.get_files_by_user_id(user.id)
    return [FileModelResponse.model_validate(file) for file in files]


############################
# Delete All Files
############################


@router.delete("/all")
async def delete_all_files(user=Depends(get_admin_user)):
    result = Files.delete_all_files()
    if result:
        try:
            Storage.delete_all_files()
        except Exception as e:
            log.exception(e)
            log.error("Error deleting files")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting files"),
            )
        return {"message": "All files deleted successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting files"),
        )


############################
# Get File By Id
############################


@router.get("/{id}", response_model=Optional[FileModelResponse])
async def get_file_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if _can_read_file(user, file):
        return FileModelResponse.model_validate(file)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Get File Data Content By Id
############################


@router.get("/{id}/status")
def get_file_processing_status(id: str, user=Depends(get_verified_user)):
    """
    Get the processing status of a file.
    Returns processing_status, processing_started_at, processing_completed_at, and processing_error if any.
    
    Status values:
    - "not_started": File has never been processed
    - "pending": Processing task is queued
    - "processing": Processing is in progress
    - "completed": Processing completed successfully
    - "error": Processing failed
    """
    # Validate UUID format (file IDs are UUIDs)
    try:
        uuid.UUID(id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file ID format",
        )
    
    file = Files.get_file_by_id(id)
    
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    
    # Check permissions
    if not _can_read_file(user, file):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    
    # Extract processing status from metadata
    meta = file.meta or {}
    processing_status = meta.get("processing_status")
    
    # Handle legacy files (uploaded before background processing feature)
    # If no status, check if file has collection_name (indicates it was processed)
    if processing_status is None:
        if meta.get("collection_name"):
            # Legacy file that was processed before status tracking was added
            processing_status = "completed"
        else:
            # File that has never been processed
            processing_status = "not_started"
    
    from open_webui.retrieval.embedding.errors import (
        FILE_PROCESSING_FAILED,
        safe_file_processing_error_code,
        safe_file_processing_error_message,
        safe_file_processing_warnings,
    )

    error_code = safe_file_processing_error_code(meta.get("processing_error_code"))
    processing_error = None
    if processing_status == "error":
        if error_code is None:
            error_code = FILE_PROCESSING_FAILED
        processing_error = safe_file_processing_error_message(error_code)

    warnings = safe_file_processing_warnings(meta.get("processing_warnings"))
    visual_summary = sanitize_public_visual_summary(meta.get("visual_summary"))

    return {
        "file_id": id,
        "filename": file.filename,
        "processing_status": processing_status,
        "processing_started_at": meta.get("processing_started_at"),
        "processing_completed_at": meta.get("processing_completed_at"),
        "processing_error": processing_error,
        "processing_error_code": error_code,
        "processing_warnings": warnings,
        "visual_summary": visual_summary,
        "collection_name": meta.get("collection_name"),
    }


@router.get("/{id}/data/content")
async def get_file_data_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if _can_read_file(user, file):
        return {"content": file.data.get("content", "")}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update File Data Content By Id
############################


class ContentForm(BaseModel):
    content: str


@router.post("/{id}/data/content/update")
async def update_file_data_content_by_id(
    request: Request,
    id: str,
    form_data: ContentForm,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
):
    file = Files.get_file_by_id(id)

    if file and (file.user_id == user.id or user.role == "admin"):
        try:
            # process_file will use job queue if available, otherwise BackgroundTasks
            process_file(
                request,
                ProcessFileForm(file_id=id, content=form_data.content),
                user=user,
                background_tasks=background_tasks,
            )
            file = Files.get_file_by_id(id=id)
        except Exception as e:
            log.exception(e)
            log.error(f"Error processing file: {file.id}")

        return {"content": file.data.get("content", "")}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Get File Content By Id
############################


@router.get("/{id}/content")
async def get_file_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)
    if _can_read_file(user, file):
        try:
            file_path = Storage.get_file(file.path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                # Handle Unicode filenames
                filename = file.meta.get("name", file.filename)
                encoded_filename = quote(filename)  # RFC5987 encoding

                content_type = file.meta.get("content_type")
                filename = file.meta.get("name", file.filename)
                encoded_filename = quote(filename)
                headers = {}

                if content_type == "application/pdf" or filename.lower().endswith(
                    ".pdf"
                ):
                    headers["Content-Disposition"] = (
                        f"inline; filename*=UTF-8''{encoded_filename}"
                    )
                    content_type = "application/pdf"
                elif content_type != "text/plain":
                    headers["Content-Disposition"] = (
                        f"attachment; filename*=UTF-8''{encoded_filename}"
                    )

                return FileResponse(file_path, headers=headers, media_type=content_type)

            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        except Exception as e:
            log.exception(e)
            log.error("Error getting file content")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error getting file content"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.get("/{id}/content/html")
async def get_html_file_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)
    if _can_read_file(user, file):
        try:
            file_path = Storage.get_file(file.path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                log.info(f"file_path: {file_path}")
                return FileResponse(file_path)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        except Exception as e:
            log.exception(e)
            log.error("Error getting file content")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error getting file content"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.get("/{id}/content/{file_name}")
async def get_file_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if _can_read_file(user, file):
        file_path = file.path

        # Handle Unicode filenames
        filename = file.meta.get("name", file.filename)
        encoded_filename = quote(filename)  # RFC5987 encoding
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }

        if file_path:
            file_path = Storage.get_file(file_path)
            file_path = Path(file_path)

            # Check if the file already exists in the cache
            if file_path.is_file():
                return FileResponse(file_path, headers=headers)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
        else:
            # File path doesn’t exist, return the content as .txt if possible
            file_content = file.content.get("content", "")
            file_name = file.filename

            # Create a generator that encodes the file content
            def generator():
                yield file_content.encode("utf-8")

            return StreamingResponse(
                generator(),
                media_type="text/plain",
                headers=headers,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Delete File By Id
############################


@router.delete("/{id}")
async def delete_file_by_id(id: str, user=Depends(get_verified_user)):
    """
    Delete a file completely from all systems.
    
    This endpoint performs complete cleanup:
    - Removes from all knowledge collections (vector DB and metadata)
    - Deletes file-specific collection from vector DB
    - Deletes from SQL database
    - Deletes physical file from storage
    """
    file = Files.get_file_by_id(id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    
    # Check permissions
    if file.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    
    log.info(
        f"Deleting file {id} (filename: {file.filename}) "
        f"by user {user.id} (email: {user.email})"
    )
    
    # Use centralized cleanup utility for complete deletion
    success, details = cleanup_file_completely(
        file_id=id,
        exclude_knowledge_id=None,  # Delete from all knowledge collections
        delete_physical_file=True,
    )
    
    if success:
        log.info(f"Successfully deleted file {id} completely")
        return {"message": "File deleted successfully"}
    else:
        # Log errors but still return success if critical operations completed
        # (SQL deletion and vector DB cleanup are critical)
        errors = details.get("errors", [])
        log.warning(
            f"File {id} deletion completed with some errors: {errors}. "
            f"Details: {details}"
        )
        
        # If critical operations failed, raise an error
        if not details.get("sql_deleted") or not details.get("vector_db_cleaned"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Error deleting file: {', '.join(errors) if errors else 'Unknown error'}"
                ),
            )
        
        # If only non-critical operations failed (like physical file deletion),
        # still return success but log the warnings
        return {
            "message": "File deleted successfully",
            "warnings": errors if errors else None,
        }
