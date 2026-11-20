"""Tests du critique et du synthetiseur, y compris leurs replis."""

from __future__ import annotations

import asyncio
import json

import pytest
from agents.agents.critic import Critic, heuristic_review, parse_review
from agents.agents.synthesizer import Synthesizer, fallback_answer
from agents.core.errors import ProviderError
from agents.core.models import LLMResponse, Review, Task, TaskResult
from agents.core.providers.scripted import ScriptedProvider

TASK = Task(id="t1", title="Calcul", instruction="calcule 2+2")
RESULT = TaskResult(
    task_id="t1", status="succeeded", output="La reponse est 4, avec detail du calcul."
)


def review_with(text: str) -> Review:
    critic = Critic(ScriptedProvider(script=[LLMResponse(text=text)]))
    return asyncio.run(critic.review(TASK, RESULT, objective="objectif"))


def test_review_accept() -> None:
    review = review_with(json.dumps({"score": 0.9, "verdict": "accept", "issues": []}))
    assert review.verdict == "accept"
    assert review.score == 0.9


def test_review_fenced_json() -> None:
    review = review_with('```json\n{"score": 0.8, "verdict": "accept"}\n```')
    assert review.verdict == "accept"


def test_review_score_is_clamped_and_verdict_derived() -> None:
    review = review_with(json.dumps({"score": 1.9, "verdict": "n-importe-quoi"}))
    assert review.score == 1.0
    assert review.verdict == "accept"


def test_review_low_score_derives_reject() -> None:
    review = review_with(json.dumps({"score": 0.1}))
    assert review.verdict == "reject"


def test_review_invalid_json_falls_back_to_heuristic() -> None:
    review = review_with("je ne sais pas evaluer")
    assert review.verdict in {"accept", "revise", "reject"}
    assert review.score > 0


def test_review_provider_error_falls_back() -> None:
    critic = Critic(ScriptedProvider(script=[ProviderError("panne")]))
    review = asyncio.run(critic.review(TASK, RESULT, objective="o"))
    assert review.score > 0


def test_review_of_failed_result_skips_llm() -> None:
    provider = ScriptedProvider(script=[])
    critic = Critic(provider)
    review = asyncio.run(
        critic.review(TASK, TaskResult(task_id="t1", status="failed", error="boom"), objective="o")
    )
    assert review.verdict == "reject"
    assert review.score == 0.0
    assert provider.calls == []


def test_heuristic_review_rejects_empty_output() -> None:
    review = heuristic_review("t1", TaskResult(task_id="t1", status="succeeded", output=""))
    assert review.verdict == "reject"


def test_parse_review_defaults() -> None:
    review = parse_review("t1", json.dumps({"verdict": "revise"}))
    assert review.score == 0.5
    assert review.verdict == "revise"


def test_synthesizer_includes_scores_and_issues() -> None:
    provider = ScriptedProvider(script=[LLMResponse(text="## Reponse\nvoici")])
    synth = Synthesizer(provider)
    answer = asyncio.run(synth.synthesize("objectif", [TASK], [RESULT], rejected=("t9",)))
    prompt = provider.calls[0][-1].content
    assert "### t1 — Calcul (score n/a)" in prompt
    assert "t9" in prompt
    assert answer.startswith("## Reponse")


def test_synthesizer_falls_back_on_empty_response() -> None:
    synth = Synthesizer(ScriptedProvider(script=[LLMResponse(text="")]))
    answer = asyncio.run(synth.synthesize("objectif", [TASK], [RESULT]))
    assert "t1" in answer
    assert "sans modele" in answer


def test_synthesizer_falls_back_on_provider_error() -> None:
    synth = Synthesizer(ScriptedProvider(script=[ProviderError("panne")]))
    answer = asyncio.run(synth.synthesize("objectif", [TASK], [RESULT]))
    assert answer


def test_fallback_answer_reports_failures() -> None:
    failed = TaskResult(task_id="t2", status="failed", error="boom")
    answer = fallback_answer("objectif", [TASK], [RESULT, failed], rejected=("t3",))
    assert "t1" in answer
    assert "t2" in answer and "t3" in answer


def test_synthesizer_handles_no_results() -> None:
    synth = Synthesizer(ScriptedProvider(script=[LLMResponse(text="")]))
    answer = asyncio.run(synth.synthesize("objectif", [TASK], []))
    assert answer


@pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
def test_review_never_exceeds_bounds(score: float) -> None:
    review = parse_review("t1", json.dumps({"score": score}))
    assert 0.0 <= review.score <= 1.0
