"""Cost accounting and budget rules for LLM calls (pure logic, no I/O).

Money is kept as integer micro-dollars (1 USD = 1_000_000) so repeated
additions never drift, and every conversion rounds *up*: the guard may
over-estimate a call but never under-count it.

A call goes through reserve -> call -> settle:

  * ``reserve`` books the worst-case cost *before* the provider is called, so
    concurrent requests cannot jointly overspend the budget;
  * ``settle`` replaces the reservation with the real cost afterwards;
  * ``release`` returns the reservation when the call fails.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

MICROS_PER_USD = 1_000_000
TOKENS_PER_MTOK = 1_000_000


class BudgetExceeded(RuntimeError):
    """The reservation would push the tenant past its budget for the period."""

    def __init__(self, tenant_id: str, period: str, requested_micros: int, available_micros: int) -> None:
        super().__init__(
            f"budget exceeded for {tenant_id} in {period}: "
            f"requested {requested_micros} micro-USD, available {max(available_micros, 0)}"
        )
        self.tenant_id = tenant_id
        self.period = period
        self.requested_micros = requested_micros
        self.available_micros = available_micros


@dataclass(frozen=True)
class Pricing:
    """Price per million tokens, in micro-USD (``3_000_000`` = 3 USD per Mtok)."""

    input_micros_per_mtok: int
    output_micros_per_mtok: int

    def cost_micros(self, input_tokens: int, output_tokens: int) -> int:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        total = input_tokens * self.input_micros_per_mtok + output_tokens * self.output_micros_per_mtok
        return -(-total // TOKENS_PER_MTOK)  # ceiling division


@dataclass(frozen=True)
class BudgetState:
    spent_micros: int = 0
    reserved_micros: int = 0

    def available(self, limit_micros: int) -> int:
        return limit_micros - self.spent_micros - self.reserved_micros


def period_for(year: int, month: int) -> str:
    """Budget periods are calendar months, e.g. ``2026-10``."""
    return f"{year:04d}-{month:02d}"


class BudgetStore(Protocol):
    def try_reserve(self, tenant_id: str, period: str, amount_micros: int, limit_micros: int) -> bool:
        """Atomically reserve ``amount_micros`` if it fits under ``limit_micros``."""

    def settle(self, tenant_id: str, period: str, reserved_micros: int, actual_micros: int) -> None:
        """Replace a reservation with the actual cost."""

    def release(self, tenant_id: str, period: str, reserved_micros: int) -> None:
        """Drop a reservation without charging anything."""

    def state(self, tenant_id: str, period: str) -> BudgetState: ...


class InMemoryBudgetStore:
    """Thread-safe store for tests and single-process use."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], BudgetState] = {}

    def try_reserve(self, tenant_id: str, period: str, amount_micros: int, limit_micros: int) -> bool:
        with self._lock:
            current = self._rows.get((tenant_id, period), BudgetState())
            if current.available(limit_micros) < amount_micros:
                return False
            self._rows[(tenant_id, period)] = BudgetState(
                current.spent_micros, current.reserved_micros + amount_micros
            )
            return True

    def settle(self, tenant_id: str, period: str, reserved_micros: int, actual_micros: int) -> None:
        with self._lock:
            current = self._rows.get((tenant_id, period), BudgetState())
            self._rows[(tenant_id, period)] = BudgetState(
                current.spent_micros + actual_micros,
                max(current.reserved_micros - reserved_micros, 0),
            )

    def release(self, tenant_id: str, period: str, reserved_micros: int) -> None:
        self.settle(tenant_id, period, reserved_micros, 0)

    def state(self, tenant_id: str, period: str) -> BudgetState:
        with self._lock:
            return self._rows.get((tenant_id, period), BudgetState())
