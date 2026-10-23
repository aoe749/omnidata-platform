"""Migration (MS SQL) and ingestion (PostgreSQL) operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_ingestion_service, get_migration_service, get_query_service, require_permission
from app.core.permissions import Action, Resource
from app.schemas.common import Page, TableParams, table_params
from app.schemas.models import (
    IngestionRequest,
    IngestionResult,
    MigrationRequest,
    MigrationRunOut,
    PublishRequest,
    PublishResult,
    QueueItemOut,
    SimulateRequest,
    SimulateResult,
)
from app.services.ingestion_service import IngestionService
from app.services.migration_service import MigrationAlreadyRunning, MigrationService
from app.services.query_services import QueryService

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/runs", response_model=Page[MigrationRunOut], dependencies=[Depends(require_permission(Resource.SYNC, Action.READ))])
def list_runs(
    state: str | None = Query(None, pattern="^(running|completed|failed)$"),
    params: TableParams = Depends(table_params),
    svc: QueryService = Depends(get_query_service),
) -> Page[MigrationRunOut]:
    return svc.runs(state, params)


@router.post("/migrate", response_model=MigrationRunOut, dependencies=[Depends(require_permission(Resource.SYNC, Action.CREATE))])
def migrate(body: MigrationRequest, svc: MigrationService = Depends(get_migration_service)) -> MigrationRunOut:
    """Start a migration run, or resume the last unfinished one."""
    try:
        return MigrationRunOut(**svc.run(body.max_batches))
    except MigrationAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/publish", response_model=PublishResult, dependencies=[Depends(require_permission(Resource.SYNC, Action.UPDATE))])
def publish(body: PublishRequest, svc: MigrationService = Depends(get_migration_service)) -> PublishResult:
    """Hand classified outbox rows over to the PostgreSQL work queue."""
    outcome = svc.publish_pending(body.max_batches)
    return PublishResult(batches=outcome.batches, published=outcome.published)


@router.post("/simulate", response_model=SimulateResult, dependencies=[Depends(require_permission(Resource.SYNC, Action.UPDATE))])
def simulate(body: SimulateRequest, svc: MigrationService = Depends(get_migration_service)) -> SimulateResult:
    """Mock upstream activity so the next migration has new and changed rows to find."""
    inserted, updated = svc.simulate_source_activity(body.new_rows, body.changed_rows)
    return SimulateResult(inserted=inserted, updated=updated)


@router.get("/queue", response_model=Page[QueueItemOut], dependencies=[Depends(require_permission(Resource.SYNC, Action.READ))])
def list_queue(
    status_filter: str | None = Query(None, alias="status", pattern="^(queued|processing|done|dead)$"),
    search: str | None = Query(None, max_length=64),
    params: TableParams = Depends(table_params),
    svc: QueryService = Depends(get_query_service),
) -> Page[QueueItemOut]:
    return svc.queue(status_filter, search, params)


@router.post("/ingest", response_model=IngestionResult, dependencies=[Depends(require_permission(Resource.SYNC, Action.UPDATE))])
def ingest(body: IngestionRequest, svc: IngestionService = Depends(get_ingestion_service)) -> IngestionResult:
    """Process queue batches in-request (the dedicated worker container does this continuously)."""
    outcome = svc.run(max_batches=body.max_batches)
    return IngestionResult(**outcome.__dict__)
