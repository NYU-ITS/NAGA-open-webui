import os
import re
import logging
from pathlib import Path
from typing import Optional

from open_webui.models.functions import (
    FunctionForm,
    FunctionMeta,
    FunctionModel,
    FunctionResponse,
    Functions,
)
from open_webui.utils.plugin import load_function_module_by_id, replace_imports
from open_webui.utils.portkey import find_workspace_portkey_key, find_workspace_portkey_url
from open_webui.config import CACHE_DIR
from open_webui.constants import ERROR_MESSAGES
from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.models import invalidate_models_cache
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


router = APIRouter()


def _derive_function_id(name: str, net_id: str) -> str:
    """Derive a stable DB ID from a function name + admin net ID.
    Lowercases, collapses any run of non-alphanumeric chars to a single '_',
    strips leading/trailing '_', falls back to 'function' if entirely special
    chars or empty. Result: sanitized_name__net_id."""
    sanitized = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_') or 'function'
    return f"{sanitized}__{net_id}"


def _prepopulate_portkey_valves(
    id: str, function_module, user_email: str | None = None
) -> None:
    """If the newly-created function declares a PORTKEY_API_KEY valve,
    pre-populate it from the calling admin's workspace Portkey key so the
    admin doesn't have to paste it in manually. Best-effort — a failure here
    must never fail function creation.

    user_email scopes the key lookup to this admin's config row. Pass None
    only for startup callers that have no request-level email available; those
    fall back to the first non-empty key across all admin rows.

    System-default functions are skipped — their valve is managed exclusively
    by the /system-default/ensure endpoint."""
    existing = Functions.get_function_by_id(id)
    if existing and existing.is_system_default:
        return

    if not hasattr(function_module, "Valves"):
        return

    Valves = function_module.Valves
    if not hasattr(Valves, "model_fields") or "PORTKEY_API_KEY" not in Valves.model_fields:
        return

    try:
        key = find_workspace_portkey_key(user_email)
        if not key:
            return
        valves: dict = {"PORTKEY_API_KEY": key}
        if "PORTKEY_API_BASE_URL" in Valves.model_fields:
            valves["PORTKEY_API_BASE_URL"] = find_workspace_portkey_url()
        Functions.update_function_valves_by_id(id, valves)
        log.info(
            "Pre-populated Portkey valves for function %s (key len=%d)", id, len(key)
        )
    except Exception:
        log.exception("Failed to pre-populate Portkey valves for function %s", id)


class EnsureSystemDefaultForm(BaseModel):
    api_key: str


############################
# EnsureAdminSystemDefault
############################


@router.post("/system-default/ensure", response_model=Optional[FunctionResponse])
async def ensure_admin_system_default(
    request: Request,
    form_data: EnsureSystemDefaultForm,
    user=Depends(get_admin_user),
):
    """Create or update this admin's personal system-default function copy,
    setting PORTKEY_API_KEY in its valve. Called when admin saves Workspace Settings.
    Each admin has exactly one is_system_default=True function owned by their email."""
    from open_webui.config import (
        DEFAULT_SYSTEM_FUNCTION_CONTENT,
        DEFAULT_SYSTEM_FUNCTION_ID,
    )

    if not form_data.api_key:
        log.warning(
            "Admin %s called ensure with empty key — skipping",
            user.email,
        )
        return None

    existing = Functions.get_admin_system_default_function(user.email)

    # Build the valve payload: key from the request + URL from workspace config.
    # Always write both so the URL stays in sync when the admin saves settings.
    workspace_url = find_workspace_portkey_url()
    valve_update = {
        "PORTKEY_API_KEY": form_data.api_key,
        "PORTKEY_API_BASE_URL": workspace_url,
    }

    if existing:
        # Merge with whatever other fields may already be stored (full-overwrite
        # model layer means we must fetch first to avoid wiping unrelated valves).
        existing_valves = Functions.get_function_valves_by_id(existing.id) or {}
        Functions.update_function_valves_by_id(
            existing.id, {**existing_valves, **valve_update}
        )
        log.info(
            "Updated system default valves for admin %s function %s (key len=%d)",
            user.email,
            existing.id,
            len(form_data.api_key),
        )
        return Functions.get_function_by_id(existing.id)

    # No existing function — create a new per-admin copy using net_id (not UUID)
    # so the ID is human-readable and stable across email changes.
    net_id = user.email.split('@')[0]
    function_id = f"{DEFAULT_SYSTEM_FUNCTION_ID}__{net_id}"
    try:
        content = replace_imports(DEFAULT_SYSTEM_FUNCTION_CONTENT)
        function_module, function_type, frontmatter = load_function_module_by_id(
            function_id, content=content
        )

        function = Functions.insert_new_function(
            user_id=user.id,
            user_email=user.email,
            type=function_type,
            form_data=FunctionForm(
                id=function_id,
                name="LLM",
                content=content,
                meta=FunctionMeta(
                    description="System default LLM pipe",
                    manifest=frontmatter,
                ),
            ),
            is_active=True,
            is_system_default=True,
        )

        if function is None:
            log.error("insert_new_function returned None for admin %s", user.email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create system default function",
            )

        # New row always has valves=NULL — no need to fetch existing.
        Functions.update_function_valves_by_id(function.id, valve_update)

        function_cache_dir = Path(CACHE_DIR) / "functions" / function_id
        function_cache_dir.mkdir(parents=True, exist_ok=True)
        request.app.state.FUNCTIONS[function_id] = function_module
        invalidate_models_cache(request)

        log.info(
            "Created system default function %s for admin %s (key len=%d)",
            function_id,
            user.email,
            len(form_data.api_key),
        )
        return Functions.get_function_by_id(function.id)

    except HTTPException:
        raise
    except Exception:
        log.exception(
            "Failed to create system default function for admin %s", user.email
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create system default function",
        )


############################
# GetFunctions
############################


@router.get("/", response_model=list[FunctionResponse])
async def get_functions(user=Depends(get_verified_user)):
    return Functions.get_functions(user.email, user=user)


############################
# ExportFunctions
############################


@router.get("/export", response_model=list[FunctionModel])
async def export_functions(user=Depends(get_admin_user)):
    return Functions.get_functions(user.email, user=user)


############################
# CreateNewFunction
############################


@router.post("/create", response_model=Optional[FunctionResponse])
async def create_new_function(
    request: Request, form_data: FunctionForm, user=Depends(get_admin_user)
):
    net_id = user.email.split('@')[0]
    function_id = _derive_function_id(form_data.name, net_id)

    # Both checks must be before the try block so HTTPException propagates
    # cleanly — the bare `except Exception` below would swallow them otherwise.
    existing_by_name = [
        f for f in Functions.get_functions(user.email, user=user)
        if f.name.lower() == form_data.name.lower()
    ]
    if existing_by_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A function with this name already exists",
        )

    if Functions.get_function_by_id(function_id) is not None:
        # Two different names can sanitize to the same ID (e.g. "My Function"
        # and "My-Function" both become my_function__net_id).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A function with a similar name already exists. "
                "Please choose a name that differs by more than punctuation or spacing."
            ),
        )

    try:
        form_data.id = function_id
        form_data.content = replace_imports(form_data.content)
        function_module, function_type, frontmatter = load_function_module_by_id(
            function_id,
            content=form_data.content,
        )
        form_data.meta.manifest = frontmatter
        request.app.state.FUNCTIONS[function_id] = function_module

        function = Functions.insert_new_function(
            user.id, user.email, function_type, form_data
        )

        function_cache_dir = Path(CACHE_DIR) / "functions" / function_id
        function_cache_dir.mkdir(parents=True, exist_ok=True)

        if function:
            _prepopulate_portkey_valves(function.id, function_module, user_email=user.email)
            invalidate_models_cache(request)
            log.info(
                "Created function '%s' (id=%s) for admin %s",
                form_data.name, function_id, user.email,
            )
            return function
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error creating function"),
            )
    except Exception as e:
        log.exception("Failed to create function '%s': %s", form_data.name, e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


############################
# GetFunctionById
############################


@router.get("/id/{id}", response_model=Optional[FunctionModel])
async def get_function_by_id(id: str, user=Depends(get_admin_user)):
    function = Functions.get_function_by_id(id)

    if function:
        return function
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# ToggleFunctionById
############################


@router.post("/id/{id}/toggle", response_model=Optional[FunctionModel])
async def toggle_function_by_id(
    request: Request, id: str, user=Depends(get_admin_user)
):
    function = Functions.get_function_by_id(id)
    if function:
        function = Functions.update_function_by_id(
            id, {"is_active": not function.is_active}
        )

        if function:
            invalidate_models_cache(request)
            return function
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating function"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# ToggleGlobalById
############################


@router.post("/id/{id}/toggle/global", response_model=Optional[FunctionModel])
async def toggle_global_by_id(
    request: Request, id: str, user=Depends(get_admin_user)
):
    function = Functions.get_function_by_id(id)
    if function:
        function = Functions.update_function_by_id(
            id, {"is_global": not function.is_global}
        )

        if function:
            invalidate_models_cache(request)
            return function
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating function"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateFunctionById
############################


@router.post("/id/{id}/update", response_model=Optional[FunctionModel])
async def update_function_by_id(
    request: Request, id: str, form_data: FunctionForm, user=Depends(get_admin_user)
):
    existing = Functions.get_function_by_id(id)
    if existing and existing.is_system_default:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System default functions cannot be edited.",
        )
    try:
        form_data.content = replace_imports(form_data.content)
        function_module, function_type, frontmatter = load_function_module_by_id(
            id, content=form_data.content
        )
        form_data.meta.manifest = frontmatter

        FUNCTIONS = request.app.state.FUNCTIONS
        FUNCTIONS[id] = function_module

        updated = {**form_data.model_dump(exclude={"id"}), "type": function_type}
        log.debug(updated)

        function = Functions.update_function_by_id(id, updated)

        if function:
            invalidate_models_cache(request)
            return function
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating function"),
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


############################
# DeleteFunctionById
############################


@router.delete("/id/{id}/delete", response_model=bool)
async def delete_function_by_id(
    request: Request, id: str, user=Depends(get_admin_user)
):
    function = Functions.get_function_by_id(id)
    if function and function.is_system_default:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System default functions cannot be deleted.",
        )

    result = Functions.delete_function_by_id(id)

    if result:
        invalidate_models_cache(request)
        FUNCTIONS = request.app.state.FUNCTIONS
        if id in FUNCTIONS:
            del FUNCTIONS[id]

    return result


############################
# GetFunctionValves
############################


@router.get("/id/{id}/valves", response_model=Optional[dict])
async def get_function_valves_by_id(id: str, user=Depends(get_admin_user)):
    function = Functions.get_function_by_id(id)
    if function:
        try:
            valves = Functions.get_function_valves_by_id(id)
            return valves
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(e),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# GetFunctionValvesSpec
############################


@router.get("/id/{id}/valves/spec", response_model=Optional[dict])
async def get_function_valves_spec_by_id(
    request: Request, id: str, user=Depends(get_admin_user)
):
    function = Functions.get_function_by_id(id)
    if function:
        if id in request.app.state.FUNCTIONS:
            function_module = request.app.state.FUNCTIONS[id]
        else:
            function_module, function_type, frontmatter = load_function_module_by_id(id)
            request.app.state.FUNCTIONS[id] = function_module

        if hasattr(function_module, "Valves"):
            Valves = function_module.Valves
            return Valves.schema()
        return None
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateFunctionValves
############################


@router.post("/id/{id}/valves/update", response_model=Optional[dict])
async def update_function_valves_by_id(
    request: Request, id: str, form_data: dict, user=Depends(get_admin_user)
):
    function = Functions.get_function_by_id(id)
    if function:
        if id in request.app.state.FUNCTIONS:
            function_module = request.app.state.FUNCTIONS[id]
        else:
            function_module, function_type, frontmatter = load_function_module_by_id(id)
            request.app.state.FUNCTIONS[id] = function_module

        if hasattr(function_module, "Valves"):
            Valves = function_module.Valves

            try:
                # Portkey fields sent as null mean "reset to workspace default"
                # (toggle flipped to Workspace). Preserve them through the None-filter
                # so the DB stores null rather than Pydantic's default "", which would
                # be read back as Custom+empty on next load (issue #14).
                _PORTKEY_FIELDS = {'PORTKEY_API_KEY', 'PORTKEY_API_BASE_URL'}
                explicitly_null_portkey = {
                    k for k, v in form_data.items()
                    if v is None and k in _PORTKEY_FIELDS
                }
                form_data = {k: v for k, v in form_data.items() if v is not None}
                valves = Valves(**form_data)
                valve_dict = valves.model_dump()
                for k in explicitly_null_portkey:
                    valve_dict[k] = None
                Functions.update_function_valves_by_id(id, valve_dict)
                invalidate_models_cache(request)
                log.debug("Updated valves for function %s", id)
                return valve_dict
            except Exception as e:
                log.exception("Error updating function valves for id %s: %s", id, e)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT(e),
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# FunctionUserValves
############################


@router.get("/id/{id}/valves/user", response_model=Optional[dict])
async def get_function_user_valves_by_id(id: str, user=Depends(get_verified_user)):
    function = Functions.get_function_by_id(id)
    if function:
        try:
            user_valves = Functions.get_user_valves_by_id_and_user_id(id, user.id)
            return user_valves
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(e),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.get("/id/{id}/valves/user/spec", response_model=Optional[dict])
async def get_function_user_valves_spec_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    function = Functions.get_function_by_id(id)
    if function:
        if id in request.app.state.FUNCTIONS:
            function_module = request.app.state.FUNCTIONS[id]
        else:
            function_module, function_type, frontmatter = load_function_module_by_id(id)
            request.app.state.FUNCTIONS[id] = function_module

        if hasattr(function_module, "UserValves"):
            UserValves = function_module.UserValves
            return UserValves.schema()
        return None
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.post("/id/{id}/valves/user/update", response_model=Optional[dict])
async def update_function_user_valves_by_id(
    request: Request, id: str, form_data: dict, user=Depends(get_verified_user)
):
    function = Functions.get_function_by_id(id)

    if function:
        if id in request.app.state.FUNCTIONS:
            function_module = request.app.state.FUNCTIONS[id]
        else:
            function_module, function_type, frontmatter = load_function_module_by_id(id)
            request.app.state.FUNCTIONS[id] = function_module

        if hasattr(function_module, "UserValves"):
            UserValves = function_module.UserValves

            try:
                form_data = {k: v for k, v in form_data.items() if v is not None}
                user_valves = UserValves(**form_data)
                Functions.update_user_valves_by_id_and_user_id(
                    id, user.id, user_valves.model_dump()
                )
                return user_valves.model_dump()
            except Exception as e:
                log.exception(f"Error updating function user valves by id {id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT(e),
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
