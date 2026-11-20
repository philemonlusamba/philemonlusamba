"""Tests du budget : les plafonds doivent etre infranchissables."""

from __future__ import annotations

import asyncio
import time

import pytest
from agents.core.budget import Budget
from agents.core.errors import BudgetExceeded
from agents.core.models import Usage


def test_consume_accumulates() -> None:
    budget = Budget(max_llm_calls=5, max_tokens=1000, max_seconds=10)
    asyncio.run(budget.consume(Usage(prompt_tokens=10, completion_tokens=5, llm_calls=1)))
    asyncio.run(budget.consume(Usage(prompt_tokens=10, completion_tokens=5, llm_calls=1)))
    assert budget.usage.llm_calls == 2
    assert budget.usage.total_tokens == 30
    assert budget.snapshot().calls_left == 3


def test_call_quota_is_enforced() -> None:
    budget = Budget(max_llm_calls=1, max_tokens=10_000, max_seconds=10)
    asyncio.run(budget.consume(Usage(llm_calls=1, prompt_tokens=1)))
    with pytest.raises(BudgetExceeded, match="appels LLM"):
        asyncio.run(budget.consume(Usage(llm_calls=1, prompt_tokens=1)))


def test_token_quota_is_enforced() -> None:
    budget = Budget(max_llm_calls=10, max_tokens=100, max_seconds=10)
    with pytest.raises(BudgetExceeded, match="tokens"):
        asyncio.run(budget.consume(Usage(prompt_tokens=80, completion_tokens=40, llm_calls=1)))


def test_deadline_is_enforced() -> None:
    budget = Budget(max_llm_calls=10, max_tokens=1000, max_seconds=0.01)
    time.sleep(0.03)
    with pytest.raises(BudgetExceeded, match="duree"):
        budget.check_deadline()
    with pytest.raises(BudgetExceeded):
        asyncio.run(budget.consume(Usage(llm_calls=1)))


def test_snapshot_exposes_remaining_resources() -> None:
    budget = Budget(max_llm_calls=4, max_tokens=100, max_seconds=10)
    snapshot = budget.snapshot()
    assert snapshot.calls_left == 4
    assert snapshot.tokens_left == 100
    assert snapshot.to_dict()["llm_calls"] == 0


def test_reset_clears_usage() -> None:
    budget = Budget(max_llm_calls=4, max_tokens=100, max_seconds=10)
    asyncio.run(budget.consume(Usage(llm_calls=1, prompt_tokens=10)))
    budget.reset()
    assert budget.usage == Usage()


@pytest.mark.parametrize(
    "kwargs",
    [{"max_llm_calls": 0}, {"max_tokens": 0}, {"max_seconds": 0}],
)
def test_invalid_limits_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        Budget(**kwargs)
