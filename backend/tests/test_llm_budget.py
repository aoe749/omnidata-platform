"""Cost guard: pricing maths, reservation rules, gateway behaviour, SQL store."""

import threading

import pytest
from sqlalchemy import create_engine, text

from app.domain.llm_budget import BudgetExceeded, InMemoryBudgetStore, Pricing, period_for
from app.repositories.llm_budget_repo import SqlBudgetStore
from app.services.llm_gateway import LlmGateway, ProviderReply, estimate_input_tokens

PRICING = Pricing(input_micros_per_mtok=3_000_000, output_micros_per_mtok=15_000_000)
PERIOD = period_for(2026, 10)


class FakeProvider:
    def __init__(self, reply=ProviderReply("ok", 100, 50), error=None):
        self.reply, self.error, self.calls = reply, error, 0

    def complete(self, prompt, max_output_tokens):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def make_sql_store():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE llm_budget_usage ("
                "tenant_id TEXT NOT NULL, period TEXT NOT NULL, "
                "spent_micros BIGINT NOT NULL DEFAULT 0 CHECK (spent_micros >= 0), "
                "reserved_micros BIGINT NOT NULL DEFAULT 0 CHECK (reserved_micros >= 0), "
                "PRIMARY KEY (tenant_id, period))"
            )
        )
    return SqlBudgetStore(engine)


@pytest.fixture(params=["memory", "sql"])
def store(request):
    return InMemoryBudgetStore() if request.param == "memory" else make_sql_store()


# ------------------------------------------------------------------ pricing
def test_cost_is_exact_for_round_numbers():
    assert PRICING.cost_micros(1_000_000, 0) == 3_000_000
    assert PRICING.cost_micros(0, 1_000_000) == 15_000_000


def test_cost_rounds_up_so_a_call_is_never_free():
    assert PRICING.cost_micros(1, 0) == 3  # 0.000003 USD, not 0
    assert Pricing(1, 1).cost_micros(1, 0) == 1


def test_negative_tokens_are_rejected():
    with pytest.raises(ValueError):
        PRICING.cost_micros(-1, 0)


def test_period_format_is_zero_padded():
    assert period_for(2026, 3) == "2026-03"


# -------------------------------------------------------------------- store
def test_reservation_that_fits_is_booked(store):
    assert store.try_reserve("t1", PERIOD, 600, limit_micros=1000)
    assert store.state("t1", PERIOD).reserved_micros == 600


def test_reservation_over_the_limit_is_refused_and_books_nothing(store):
    assert store.try_reserve("t1", PERIOD, 600, limit_micros=1000)
    assert not store.try_reserve("t1", PERIOD, 401, limit_micros=1000)
    assert store.state("t1", PERIOD).reserved_micros == 600


def test_reservation_up_to_the_exact_limit_is_allowed(store):
    assert store.try_reserve("t1", PERIOD, 1000, limit_micros=1000)
    assert not store.try_reserve("t1", PERIOD, 1, limit_micros=1000)


def test_settle_swaps_reservation_for_actual_cost(store):
    store.try_reserve("t1", PERIOD, 600, limit_micros=1000)
    store.settle("t1", PERIOD, reserved_micros=600, actual_micros=250)
    state = store.state("t1", PERIOD)
    assert (state.spent_micros, state.reserved_micros) == (250, 0)


def test_release_returns_the_reservation_without_charging(store):
    store.try_reserve("t1", PERIOD, 600, limit_micros=1000)
    store.release("t1", PERIOD, 600)
    state = store.state("t1", PERIOD)
    assert (state.spent_micros, state.reserved_micros) == (0, 0)


def test_tenants_and_periods_are_independent(store):
    assert store.try_reserve("t1", PERIOD, 1000, limit_micros=1000)
    assert store.try_reserve("t2", PERIOD, 1000, limit_micros=1000)
    assert store.try_reserve("t1", period_for(2026, 11), 1000, limit_micros=1000)


def test_unknown_tenant_has_empty_state(store):
    state = store.state("nobody", PERIOD)
    assert (state.spent_micros, state.reserved_micros) == (0, 0)


def test_concurrent_reservations_never_exceed_the_limit():
    store = InMemoryBudgetStore()
    granted = []

    def worker():
        granted.append(store.try_reserve("t1", PERIOD, 100, limit_micros=1000))

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(granted) == 10
    assert store.state("t1", PERIOD).reserved_micros == 1000


# ------------------------------------------------------------------ gateway
def test_gateway_charges_actual_usage_not_the_reservation(store):
    provider = FakeProvider(ProviderReply("hello", input_tokens=100, output_tokens=50))
    gateway = LlmGateway(provider, PRICING, store)

    result = gateway.complete(tenant_id="t1", period=PERIOD, limit_micros=10_000, prompt="hi", max_output_tokens=512)

    assert result.text == "hello"
    assert result.cost_micros == PRICING.cost_micros(100, 50)
    state = store.state("t1", PERIOD)
    assert state.spent_micros == result.cost_micros
    assert state.reserved_micros == 0


def test_gateway_refuses_before_calling_the_provider(store):
    provider = FakeProvider()
    gateway = LlmGateway(provider, PRICING, store)

    with pytest.raises(BudgetExceeded) as exc:
        gateway.complete(tenant_id="t1", period=PERIOD, limit_micros=10, prompt="hi", max_output_tokens=512)

    assert provider.calls == 0
    assert exc.value.requested_micros > exc.value.available_micros
    assert store.state("t1", PERIOD).reserved_micros == 0


def test_gateway_releases_the_reservation_when_the_provider_fails(store):
    provider = FakeProvider(error=TimeoutError("upstream timeout"))
    gateway = LlmGateway(provider, PRICING, store)

    with pytest.raises(TimeoutError):
        gateway.complete(tenant_id="t1", period=PERIOD, limit_micros=10_000, prompt="hi", max_output_tokens=100)

    state = store.state("t1", PERIOD)
    assert (state.spent_micros, state.reserved_micros) == (0, 0)


def test_budget_runs_out_after_repeated_calls(store):
    provider = FakeProvider(ProviderReply("x", input_tokens=10, output_tokens=100))
    gateway = LlmGateway(provider, PRICING, store)
    per_call = PRICING.cost_micros(10, 100)
    limit = per_call * 3 + 50

    for _ in range(3):
        gateway.complete(tenant_id="t1", period=PERIOD, limit_micros=limit, prompt="x" * 40, max_output_tokens=100)
    with pytest.raises(BudgetExceeded):
        gateway.complete(tenant_id="t1", period=PERIOD, limit_micros=limit, prompt="x" * 40, max_output_tokens=100)

    assert provider.calls == 3


def test_invalid_output_cap_is_rejected(store):
    gateway = LlmGateway(FakeProvider(), PRICING, store)
    with pytest.raises(ValueError):
        gateway.complete(tenant_id="t1", period=PERIOD, limit_micros=100, prompt="hi", max_output_tokens=0)


def test_token_estimate_is_at_least_one_and_rounds_up():
    assert estimate_input_tokens("") == 1
    assert estimate_input_tokens("abcde") == 2
