"""Stable-ID admin inheritance, config/credential lookup, and frozen execution context."""

import logging
from dataclasses import dataclass
from typing import Optional

from open_webui.models.users import Users
from open_webui.models.groups import Groups
from open_webui.models.embeddings import EmbeddingModel
from .inputs import EmbeddingModelSpec
from .errors import (
    EmbeddingError,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_MODEL_DISABLED,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_ADMIN_AMBIGUOUS,
    EMBEDDING_CREDENTIALS_MISSING,
    EMBEDDING_MODEL_SPACE_MIXED,
    EMBEDDING_PROVIDER_UNSUPPORTED,
)
from .registry import get_model_spec_by_name, get_model_spec_by_id

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingExecutionContext:
    """
    Frozen execution context containing only stable IDs and model spec.
    Contains no credentials, emails, or provider-specific details.
    """
    admin_id: str
    model: EmbeddingModelSpec


def resolve_admin_for_user(user_id: str):
    """
    Resolve the effective admin for a user using stable IDs.
    
    If the user is an admin, return them directly.
    Otherwise, collect group owners, retain only current admins,
    and fail on zero or more than one distinct admin ID.
    
    Args:
        user_id: The user ID to resolve admin for.
        
    Returns:
        The admin user object.
        
    Raises:
        EmbeddingError: If admin cannot be resolved or is ambiguous.
    """
    subject = Users.get_user_by_id(user_id)
    if subject is None:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"User {user_id} not found.",
        )
    
    # If user is admin, return directly
    if subject.role == "admin":
        return subject
    
    # Collect group owners
    groups = Groups.get_groups_by_member_id(user_id)
    admin_ids = {group.user_id for group in groups if group.user_id}
    
    # Load each owner and check if they're admin
    admins = []
    for admin_id in admin_ids:
        owner = Users.get_user_by_id(admin_id)
        if owner and owner.role == "admin":
            admins.append(owner)
    
    if len(admins) == 0:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"No admin found for user {user_id}.",
        )
    
    if len(admins) != 1:
        admin_ids_found = [a.id for a in admins]
        raise EmbeddingError(
            EMBEDDING_ADMIN_AMBIGUOUS,
            detail=f"Ambiguous admin resolution for user {user_id}: {admin_ids_found}.",
        )
    
    return admins[0]


def resolve_admin_for_knowledge(knowledge_id: str, requesting_user_id: str):
    """
    Resolve admin for a knowledge base.
    Loads the knowledge owner and resolves that owner through stable-ID rule.
    
    Args:
        knowledge_id: The knowledge base ID.
        requesting_user_id: The user requesting the operation.
        
    Returns:
        The admin user object.
        
    Raises:
        EmbeddingError: If admin cannot be resolved or is ambiguous.
    """
    from open_webui.models.knowledge import Knowledges
    
    knowledge = Knowledges.get_knowledge_by_id(knowledge_id)
    if knowledge is None or knowledge.user_id is None:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"Knowledge {knowledge_id} not found or has no owner.",
        )
    
    # Resolve the knowledge owner through stable-ID rule
    return resolve_admin_for_user(knowledge.user_id)


def resolve_admin_for_admin_id(admin_id: str):
    """
    Reload and verify an admin at execution time.
    
    Args:
        admin_id: The admin user ID to verify.
        
    Returns:
        The admin user object.
        
    Raises:
        EmbeddingError: If admin is not found or not actually an admin.
    """
    admin = Users.get_user_by_id(admin_id)
    if admin is None:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"Admin {admin_id} not found.",
        )
    
    if admin.role != "admin":
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"User {admin_id} is not an admin.",
        )
    
    return admin


def resolve_model_for_admin(admin_email: str, config) -> EmbeddingModelSpec:
    """
    Resolve the embedding model for an admin using the config.
    
    Args:
        admin_email: The admin's email.
        config: The app config (request.app.state.config).
        
    Returns:
        EmbeddingModelSpec for the enabled model.
        
    Raises:
        EmbeddingError: If model not configured, not found, or not enabled.
    """
    # Get the model name from config
    model_name = config.RAG_EMBEDDING_MODEL_USER.get(admin_email)
    if not model_name or not model_name.strip():
        raise EmbeddingError(
            EMBEDDING_MODEL_NOT_CONFIGURED,
            detail=f"No embedding model configured for {admin_email}.",
        )
    
    # Look up the model in the registry
    return get_model_spec_by_name(model_name)


def resolve_credential_for_admin(admin_email: str, model: EmbeddingModelSpec, config) -> str:
    """
    Resolve the provider-specific credential for an admin.
    
    Args:
        admin_email: The admin's email.
        model: The embedding model spec.
        config: The app config (request.app.state.config).
        
    Returns:
        The provider-specific credential (API key).
        
    Raises:
        EmbeddingError: If credentials are missing or provider unsupported.
    """
    if model.provider != "portkey":
        raise EmbeddingError(
            EMBEDDING_PROVIDER_UNSUPPORTED,
            detail=f"Unsupported provider: {model.provider}.",
        )
    
    # Get the API key from config
    api_key = config.RAG_OPENAI_API_KEY.get(admin_email)
    if not api_key or not api_key.strip():
        raise EmbeddingError(
            EMBEDDING_CREDENTIALS_MISSING,
            detail=f"No embedding API key configured for {admin_email}.",
        )
    return api_key


def resolve_base_url_for_admin(model: EmbeddingModelSpec, config) -> str:
    """
    Resolve the provider-specific base URL.
    
    Args:
        model: The embedding model spec.
        config: The app config (request.app.state.config).
        
    Returns:
        The provider-specific base URL.
        
    Raises:
        EmbeddingError: If provider unsupported or base URL cannot be resolved.
    """
    if model.provider != "portkey":
        raise EmbeddingError(
            EMBEDDING_PROVIDER_UNSUPPORTED,
            detail=f"Unsupported provider: {model.provider}.",
        )
    
    base_url_config = config.RAG_OPENAI_API_BASE_URL
    base_url = (
        base_url_config.value
        if hasattr(base_url_config, 'value')
        else str(base_url_config)
    )
    
    # NYU gateway fallback for Portkey
    if not base_url or base_url.strip() == "" or base_url == "None":
        base_url = "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
        log.warning(f"RAG_OPENAI_API_BASE_URL is empty, using default: {base_url}")
    
    return base_url


def resolve_for_user(user_id: str, config) -> EmbeddingExecutionContext:
    """
    Resolve execution context for a user.
    
    Args:
        user_id: The user ID.
        config: The app config.
        
    Returns:
        EmbeddingExecutionContext with admin_id and model spec.
        
    Raises:
        EmbeddingError: If resolution fails.
    """
    admin = resolve_admin_for_user(user_id)
    model = resolve_model_for_admin(admin.email, config)
    return EmbeddingExecutionContext(admin_id=admin.id, model=model)


def resolve_for_admin_id(admin_id: str, config) -> EmbeddingExecutionContext:
    """
    Resolve execution context for a known admin ID.
    
    Args:
        admin_id: The admin user ID.
        config: The app config.
        
    Returns:
        EmbeddingExecutionContext with admin_id and model spec.
        
    Raises:
        EmbeddingError: If resolution fails.
    """
    admin = resolve_admin_for_admin_id(admin_id)
    model = resolve_model_for_admin(admin.email, config)
    return EmbeddingExecutionContext(admin_id=admin.id, model=model)


def resolve_frozen(admin_id: str, embedding_model_id: str) -> EmbeddingExecutionContext:
    """
    Resolve execution context from frozen (enqueued) admin_id and embedding_model_id.
    Reloads the admin at execution time to get current email.
    
    Args:
        admin_id: The frozen admin user ID.
        embedding_model_id: The frozen embedding model ID.
        
    Returns:
        EmbeddingExecutionContext with admin_id and model spec.
        
    Raises:
        EmbeddingError: If resolution fails.
    """
    # Reload admin at execution time to get current email
    admin = resolve_admin_for_admin_id(admin_id)
    
    # Look up the model by ID
    model = get_model_spec_by_id(embedding_model_id)
    
    return EmbeddingExecutionContext(admin_id=admin.id, model=model)


def freeze_for_enqueue(user_id: str, config) -> tuple[str, str]:
    """
    Resolve admin and registry model before enqueue.
    Returns exactly admin_id plus embedding_model_id; no email, model string, key, etc.
    
    Args:
        user_id: The user ID to resolve admin for.
        config: The app config.
        
    Returns:
        Tuple of (admin_id, embedding_model_id).
        
    Raises:
        EmbeddingError: If resolution fails.
    """
    admin = resolve_admin_for_user(user_id)
    model = resolve_model_for_admin(admin.email, config)
    return (admin.id, model.id)


def freeze_for_knowledge_enqueue(knowledge_id: str, requesting_user_id: str, config) -> tuple[str, str]:
    """
    Resolve admin and registry model for knowledge uploads before enqueue.
    Returns exactly admin_id plus embedding_model_id; no email, model string, key, etc.
    
    Args:
        knowledge_id: The knowledge base ID.
        requesting_user_id: The user requesting the operation.
        config: The app config.
        
    Returns:
        Tuple of (admin_id, embedding_model_id).
        
    Raises:
        EmbeddingError: If resolution fails.
    """
    admin = resolve_admin_for_knowledge(knowledge_id, requesting_user_id)
    model = resolve_model_for_admin(admin.email, config)
    return (admin.id, model.id)


def resolve_model_space_for_knowledge(knowledge_id: str, config) -> tuple[str, str]:
    """
    Resolve the (admin_id, embedding_model_id) provenance space a knowledge base
    belongs to.

    A knowledge base resolves to its owning admin (RBAC group owner), and the
    model is that admin's currently selected registry model.

    Args:
        knowledge_id: The knowledge base ID.
        config: The app config.

    Returns:
        Tuple of (admin_id, embedding_model_id).

    Raises:
        EmbeddingError: If resolution fails.
    """
    admin = resolve_admin_for_knowledge(knowledge_id, requesting_user_id=None)
    model = resolve_model_for_admin(admin.email, config)
    return (admin.id, model.id)


def assert_single_model_space(
    requesting_user_id: str,
    knowledge_ids,
    config,
) -> tuple[str, str]:
    """
    Resolve the requesting user's effective (admin_id, embedding_model_id) space
    and assert every supplied knowledge base resolves to the same space.

    A retrieval request that mixes embedding model spaces is rejected so a query
    vector is never compared with document vectors from another model.

    Args:
        requesting_user_id: The user issuing the retrieval request.
        knowledge_ids: Iterable of knowledge base IDs in the request.
        config: The app config.

    Returns:
        The single effective (admin_id, embedding_model_id) for the request.

    Raises:
        EmbeddingError: EMBEDDING_MODEL_SPACE_MIXED if any knowledge base
            resolves to a different space than the requesting user.
    """
    admin = resolve_admin_for_user(requesting_user_id)
    model = resolve_model_for_admin(admin.email, config)
    effective = (admin.id, model.id)

    for knowledge_id in knowledge_ids or []:
        space = resolve_model_space_for_knowledge(knowledge_id, config)
        if space != effective:
            raise EmbeddingError(
                EMBEDDING_MODEL_SPACE_MIXED,
                detail=(
                    f"Knowledge base {knowledge_id} resolves to model space {space}, "
                    f"expected {effective}."
                ),
            )

    return effective
