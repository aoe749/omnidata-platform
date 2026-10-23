"""Read APIs: transactions table + CSV export, dashboard statistics, user administration."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.api.deps import get_query_service, require_permission
from app.core.permissions import Action, Principal, Resource
from app.schemas.common import Page, TableParams, table_params
from app.schemas.models import Overview, TransactionOut, UserOut
from app.services.query_services import QueryService, TransactionFilters

router = APIRouter(tags=["data"])


def transaction_filters(
    search: str | None = Query(None, max_length=64),
    currency: str | None = Query(None, pattern="^[A-Za-z]{3}$"),
    status: str | None = Query(None, pattern="^(pending|settled|reversed)$"),
    min_amount_cents: int | None = Query(None, ge=0),
    max_amount_cents: int | None = Query(None, ge=0),
    occurred_from: date | None = None,
    occurred_to: date | None = None,
) -> TransactionFilters:
    return TransactionFilters(
        search, currency, status, min_amount_cents, max_amount_cents, occurred_from, occurred_to
    )


@router.get(
    "/transactions",
    response_model=Page[TransactionOut],
    dependencies=[Depends(require_permission(Resource.TRANSACTIONS, Action.READ))],
)
def list_transactions(
    filters: TransactionFilters = Depends(transaction_filters),
    params: TableParams = Depends(table_params),
    svc: QueryService = Depends(get_query_service),
) -> Page[TransactionOut]:
    return svc.transactions(filters, params)


@router.get(
    "/transactions/export",
    dependencies=[Depends(require_permission(Resource.TRANSACTIONS, Action.EXPORT))],
)
def export_transactions(
    filters: TransactionFilters = Depends(transaction_filters),
    svc: QueryService = Depends(get_query_service),
) -> StreamingResponse:
    return StreamingResponse(
        svc.export_transactions_csv(filters),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )


@router.get(
    "/stats/overview",
    response_model=Overview,
    dependencies=[Depends(require_permission(Resource.METRICS, Action.READ))],
)
def overview(svc: QueryService = Depends(get_query_service)) -> Overview:
    return svc.overview()


@router.get(
    "/users",
    response_model=list[UserOut],
    dependencies=[Depends(require_permission(Resource.USERS, Action.READ))],
)
def list_users(svc: QueryService = Depends(get_query_service)) -> list[UserOut]:
    return svc.users()


@router.delete("/users/{user_id}", status_code=204)
def deactivate_user(
    user_id: int,
    principal: Principal = Depends(require_permission(Resource.USERS, Action.DELETE)),
    svc: QueryService = Depends(get_query_service),
) -> Response:
    if user_id == principal.user_id:
        raise HTTPException(409, "You cannot deactivate your own account")
    if not svc.deactivate_user(user_id):
        raise HTTPException(404, "User not found or already inactive")
    return Response(status_code=204)
