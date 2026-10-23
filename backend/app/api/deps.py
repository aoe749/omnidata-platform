"""FastAPI dependencies: service wiring, authentication, bitmask authorisation."""

from __future__ import annotations

import uuid
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.permissions import Action, Principal, Resource, describe_mask
from app.db.engines import DatabaseRegistry, get_registry
from app.services.auth_service import AuthError, AuthService
from app.services.ingestion_service import IngestionService
from app.services.migration_service import MigrationService
from app.services.query_services import QueryService

_bearer = HTTPBearer(auto_error=False)


def get_auth_service(
    registry: DatabaseRegistry = Depends(get_registry), settings: Settings = Depends(get_settings)
) -> AuthService:
    return AuthService(registry, settings)


def get_migration_service(
    registry: DatabaseRegistry = Depends(get_registry), settings: Settings = Depends(get_settings)
) -> MigrationService:
    return MigrationService(registry, settings)


def get_ingestion_service(
    registry: DatabaseRegistry = Depends(get_registry), settings: Settings = Depends(get_settings)
) -> IngestionService:
    return IngestionService(registry, settings, worker_id=f"api-{uuid.uuid4().hex[:6]}")


def get_query_service(registry: DatabaseRegistry = Depends(get_registry)) -> QueryService:
    return QueryService(registry)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> Principal:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    try:
        return auth.principal_from_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc), {"WWW-Authenticate": "Bearer"}) from exc


def require_permission(resource: Resource, action: Action) -> Callable[..., Principal]:
    """Route guard: ``Depends(require_permission(Resource.SYNC, Action.CREATE))``.

    The check is one bitwise AND against the mask stored for the caller's role.
    """

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.can(resource, action):
            granted = describe_mask(principal.permissions.get(resource.value, 0)) or ["none"]
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Missing '{action.name.lower()}' permission on '{resource.value}' (granted: {', '.join(granted)})",
            )
        return principal

    return dependency
