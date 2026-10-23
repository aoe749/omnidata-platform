"""SQL-backed budget store.

The budget check is a single conditional ``UPDATE``: the row lock serialises
concurrent reservations for one tenant and period, and the ``WHERE`` clause
refuses a reservation that does not fit. No read-then-write race exists, and
the statements are portable (PostgreSQL in production, SQLite in unit tests).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.engines import session_scope
from app.domain.llm_budget import BudgetState


class SqlBudgetStore:
    """Implements ``BudgetStore``; every method is one short transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def try_reserve(self, tenant_id: str, period: str, amount_micros: int, limit_micros: int) -> bool:
        params = {"t": tenant_id, "p": period, "a": amount_micros, "limit": limit_micros}
        with session_scope(self.engine) as session:
            session.execute(
                text(
                    "INSERT INTO llm_budget_usage (tenant_id, period) VALUES (:t, :p) "
                    "ON CONFLICT (tenant_id, period) DO NOTHING"
                ),
                params,
            )
            result = session.execute(
                text(
                    "UPDATE llm_budget_usage SET reserved_micros = reserved_micros + :a "
                    "WHERE tenant_id = :t AND period = :p "
                    "AND spent_micros + reserved_micros + :a <= :limit"
                ),
                params,
            )
            return result.rowcount == 1

    def settle(self, tenant_id: str, period: str, reserved_micros: int, actual_micros: int) -> None:
        with session_scope(self.engine) as session:
            session.execute(
                text(
                    "UPDATE llm_budget_usage SET "
                    "spent_micros = spent_micros + :actual, "
                    "reserved_micros = CASE WHEN reserved_micros >= :reserved THEN reserved_micros - :reserved ELSE 0 END "
                    "WHERE tenant_id = :t AND period = :p"
                ),
                {"t": tenant_id, "p": period, "reserved": reserved_micros, "actual": actual_micros},
            )

    def release(self, tenant_id: str, period: str, reserved_micros: int) -> None:
        self.settle(tenant_id, period, reserved_micros, 0)

    def state(self, tenant_id: str, period: str) -> BudgetState:
        with session_scope(self.engine) as session:
            row = session.execute(
                text("SELECT spent_micros, reserved_micros FROM llm_budget_usage WHERE tenant_id = :t AND period = :p"),
                {"t": tenant_id, "p": period},
            ).one_or_none()
        return BudgetState(*row) if row else BudgetState()
