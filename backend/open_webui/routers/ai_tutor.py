import logging

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from open_webui.env import AI_TUTOR_API_BASE_URL, SRC_LOG_LEVELS
from open_webui.utils.auth import get_verified_user


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

FORWARDED_HEADER_ALLOWLIST = {
    "authorization",
    "content-type",
    "accept",
}

RESPONSE_HEADER_BLOCKLIST = {
    "content-encoding",
    "content-length",
    "connection",
    "transfer-encoding",
}


def build_upstream_url(path: str) -> str:
    base_url = AI_TUTOR_API_BASE_URL.rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Tutor upstream is not configured.",
        )

    if not path:
        return f"{base_url}/"

    return f"{base_url}/{path.lstrip('/')}"


def get_forward_headers(request: Request) -> dict[str, str]:
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() in FORWARDED_HEADER_ALLOWLIST
    }


def build_response_headers(upstream_response: requests.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in RESPONSE_HEADER_BLOCKLIST
    }


async def proxy_ai_tutor_request(request: Request, path: str, _user=Depends(get_verified_user)):
    upstream_url = build_upstream_url(path)
    request_body = await request.body()

    try:
        upstream_response = requests.request(
            method=request.method,
            url=upstream_url,
            headers=get_forward_headers(request),
            params=list(request.query_params.multi_items()),
            data=request_body if request_body else None,
            timeout=300,
        )
    except requests.RequestException as exc:
        log.exception("AI Tutor proxy connection error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI Tutor service is unavailable.",
        ) from exc

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=build_response_headers(upstream_response),
        media_type=upstream_response.headers.get("content-type"),
    )


@router.api_route("", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_ai_tutor_root(request: Request, user=Depends(get_verified_user)):
    return await proxy_ai_tutor_request(request, "", user)


@router.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_ai_tutor_path(
    path: str, request: Request, user=Depends(get_verified_user)
):
    return await proxy_ai_tutor_request(request, path, user)
