"""Budget-guarded gateway in front of any LLM provider.

The gateway knows nothing about a vendor: it needs a ``LlmProvider`` that turns
a prompt into text plus token counts. That keeps the cost guard testable
without network access and lets the same rules wrap any provider SDK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.domain.llm_budget import BudgetExceeded, BudgetStore, Pricing

log = logging.getLogger(__name__)

# Rough size estimate used only to size the reservation; the provider's real
# token counts are what get charged.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ProviderReply:
    text: str
    input_tokens: int
    output_tokens: int


class LlmProvider(Protocol):
    def complete(self, prompt: str, max_output_tokens: int) -> ProviderReply: ...


@dataclass(frozen=True)
class GatewayResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_micros: int


def estimate_input_tokens(prompt: str) -> int:
    return max(1, -(-len(prompt) // CHARS_PER_TOKEN))


class LlmGateway:
    def __init__(self, provider: LlmProvider, pricing: Pricing, store: BudgetStore) -> None:
        self.provider = provider
        self.pricing = pricing
        self.store = store

    def complete(
        self,
        *,
        tenant_id: str,
        period: str,
        limit_micros: int,
        prompt: str,
        max_output_tokens: int = 512,
    ) -> GatewayResult:
        """Run one completion if the tenant can afford its worst case.

        The reservation assumes the model uses ``max_output_tokens``; the
        provider is never called for a request that could not be paid for.
        """
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")

        worst_case = self.pricing.cost_micros(estimate_input_tokens(prompt), max_output_tokens)
        if not self.store.try_reserve(tenant_id, period, worst_case, limit_micros):
            available = limit_micros - self._committed(tenant_id, period)
            raise BudgetExceeded(tenant_id, period, worst_case, available)

        try:
            reply = self.provider.complete(prompt, max_output_tokens)
        except Exception:
            self.store.release(tenant_id, period, worst_case)
            raise

        actual = self.pricing.cost_micros(reply.input_tokens, reply.output_tokens)
        # A provider that overruns the estimate is still charged in full; the
        # next reservation sees the higher spend.
        self.store.settle(tenant_id, period, worst_case, actual)
        if actual > worst_case:
            log.warning("LLM cost %s exceeded its reservation %s for %s", actual, worst_case, tenant_id)
        return GatewayResult(reply.text, reply.input_tokens, reply.output_tokens, actual)

    def _committed(self, tenant_id: str, period: str) -> int:
        state = self.store.state(tenant_id, period)
        return state.spent_micros + state.reserved_micros
