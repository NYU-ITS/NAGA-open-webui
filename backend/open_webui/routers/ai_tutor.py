import logging

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from open_webui.env import AI_TUTOR_API_BASE_URL, SRC_LOG_LEVELS
from open_webui.utils.auth import get_verified_user
from open_webui.utils.super_admin import is_super_admin
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.groups import Groups


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

# Instructor-only endpoints that require admin role
INSTRUCTOR_ONLY_PATHS = {
    '/student-analysis',
    '/topic-analysis',
    '/instructor-setup',
}

# Endpoints where students must be scoped to their own data via student_id or user_id parameter
STUDENT_SCOPED_ENDPOINTS = {
    '/homework',
    '/practice',
    '/assignment',
    '/analysis',
}


def is_instructor_only_path(path: str) -> bool:
    """Check if a path requires instructor/admin access."""
    normalized_path = path.lstrip('/')
    return any(normalized_path.startswith(prefix.lstrip('/')) for prefix in INSTRUCTOR_ONLY_PATHS)


def is_student_scoped_endpoint(path: str) -> bool:
    """Check if a path requires student data scoping."""
    normalized_path = path.lstrip('/')
    return any(normalized_path.startswith(prefix.lstrip('/')) for prefix in STUDENT_SCOPED_ENDPOINTS)


def user_can_access_group(user_id: str, user_role: str, group_id: str, user=None) -> bool:
    """
    Check if a user can access a specific group.

    Superadmins can access all groups.
    Instructors can access groups they own or are members of.
    Students can access groups they are members of.
    """
    try:
        # Superadmins can access any group
        if user and is_super_admin(user):
            return True

        group = Groups.get_group_by_id(group_id)
        if not group:
            return False

        # Instructors/admins can access groups they own or are members of
        if user_role == "admin":
            return group.user_id == user_id or user_id in (group.user_ids or [])

        # Students can only access groups they are members of
        return user_id in (group.user_ids or [])
    except Exception as e:
        log.error(f"Error checking group access for user {user_id}: {e}")
        return False

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
    # Check if this is an instructor-only endpoint
    if is_instructor_only_path(path) and _user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only instructors can access this endpoint.",
        )

    # Get group_id from query parameters - required for most endpoints
    group_id = request.query_params.get("group_id")

    # Validate group access if group_id is provided
    if group_id:
        if not user_can_access_group(_user.id, _user.role, group_id, _user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this group.",
            )

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
