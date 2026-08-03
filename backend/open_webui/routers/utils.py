import black
import logging
import markdown

from open_webui.models.chats import ChatTitleMessagesForm
from open_webui.config import DATA_DIR, ENABLE_ADMIN_EXPORT
from open_webui.constants import ERROR_MESSAGES
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse


from open_webui.utils.misc import get_gravatar_url
from open_webui.utils import pdf_jobs
from open_webui.utils.pdf_generator import PDFGenerator
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.code_interpreter import execute_code_jupyter
from open_webui.env import SRC_LOG_LEVELS


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


@router.get("/gravatar")
async def get_gravatar(email: str, user=Depends(get_verified_user)):
    return get_gravatar_url(email)


class CodeForm(BaseModel):
    code: str


@router.post("/code/format")
async def format_code(form_data: CodeForm, user=Depends(get_verified_user)):
    try:
        formatted_code = black.format_str(form_data.code, mode=black.Mode())
        return {"code": formatted_code}
    except black.NothingChanged:
        return {"code": form_data.code}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/code/execute")
async def execute_code(
    request: Request, form_data: CodeForm, user=Depends(get_verified_user)
):
    if request.app.state.config.CODE_EXECUTION_ENGINE == "jupyter":
        output = await execute_code_jupyter(
            request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
            form_data.code,
            (
                request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN
                if request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH == "token"
                else None
            ),
            (
                request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD
                if request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH == "password"
                else None
            ),
            request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        )

        return output
    else:
        raise HTTPException(
            status_code=400,
            detail="Code execution engine not supported",
        )


class MarkdownForm(BaseModel):
    md: str


@router.post("/markdown")
async def get_html_from_markdown(
    form_data: MarkdownForm, user=Depends(get_verified_user)
):
    return {"html": markdown.markdown(form_data.md)}


class ChatForm(BaseModel):
    title: str
    messages: list[dict]


@router.post("/pdf")
async def download_chat_as_pdf(
    form_data: ChatTitleMessagesForm, user=Depends(get_verified_user)
):
    try:
        # PDF generation is synchronous and CPU bound. Running it inline would
        # hold the event loop, and with it every other request this worker is
        # serving, for the whole export.
        pdf_bytes = await run_in_threadpool(PDFGenerator(form_data).generate_chat_pdf)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment;filename=chat.pdf"},
        )
    except Exception as e:
        log.exception(f"Error generating PDF: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pdf/jobs")
async def create_chat_pdf_job(
    form_data: ChatTitleMessagesForm, user=Depends(get_verified_user)
):
    """Queue a PDF export and return a job id to poll."""
    try:
        job_id = pdf_jobs.submit(form_data, user.id)
        return {"id": job_id, "status": pdf_jobs.STATUS_PENDING}
    except Exception as e:
        log.exception(f"Error queueing PDF export: {e}")
        raise HTTPException(status_code=400, detail=str(e))


def _get_owned_job(job_id: str, user):
    job = pdf_jobs.status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="PDF export job not found")
    if job.get("user_id") and job["user_id"] != user.id:
        raise HTTPException(status_code=403, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)
    return job


@router.get("/pdf/jobs/{job_id}")
async def get_chat_pdf_job(job_id: str, user=Depends(get_verified_user)):
    job = _get_owned_job(job_id, user)
    return {
        "id": job["id"],
        "status": job["status"],
        "size": job["size"],
        "error": job["error"],
    }


@router.get("/pdf/jobs/{job_id}/download")
async def download_chat_pdf_job(job_id: str, user=Depends(get_verified_user)):
    job = _get_owned_job(job_id, user)

    if job["status"] == pdf_jobs.STATUS_ERROR:
        raise HTTPException(status_code=400, detail=job.get("error") or "PDF export failed")
    if job["status"] != pdf_jobs.STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="PDF export is not finished yet")

    pdf_bytes = pdf_jobs.result(job_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="PDF export result expired")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment;filename=chat.pdf"},
    )


@router.get("/db/download")
async def download_db(user=Depends(get_admin_user)):
    if not ENABLE_ADMIN_EXPORT:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    from open_webui.internal.db import engine

    if engine.name != "sqlite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DB_NOT_SQLITE,
        )
    return FileResponse(
        engine.url.database,
        media_type="application/octet-stream",
        filename="webui.db",
    )


@router.get("/litellm/config")
async def download_litellm_config_yaml(user=Depends(get_admin_user)):
    return FileResponse(
        f"{DATA_DIR}/litellm/config.yaml",
        media_type="application/octet-stream",
        filename="config.yaml",
    )
