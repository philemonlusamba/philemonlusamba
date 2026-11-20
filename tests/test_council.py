"""Tests du conseil multi-modeles : deliberation, anonymisation, pannes, juge."""

from __future__ import annotations

import json
import time

import pytest
from agents.core.budget import Budget
from agents.core.bus import CollectorSink, EventBus
from agents.core.errors import AgentError, ProviderError
from agents.core.models import LLMResponse
from agents.core.providers.mock import MockProvider
from agents.core.providers.scripted import ScriptedProvider
from agents.council import Contribution, Council, CouncilConfig, Member

QUESTION = "Faut-il un index SQL ou une recherche plein texte pour 50 000 documents ?"


def mock_members(*labels: str, delay: float = 0.0) -> list[Member]:
    return [
        Member(label=label, provider=MockProvider(model=label.lower(), delay_s=delay))
        for label in labels
    ]


def build(members=None, **kwargs) -> Council:
    return Council(members or mock_members("ChatGPT", "Claude", "Gemini"), **kwargs)


# ------------------------------------------------------------ deliberation
def test_three_members_deliberate() -> None:
    council = build(config=CouncilConfig(rounds=1))
    report = council.deliberate_sync(QUESTION)
    assert report.status == "succeeded"
    assert report.members == ("ChatGPT", "Claude", "Gemini")
    assert len(report.contributions) == 3
    assert all(item.ok for item in report.contributions)
    assert report.judge == "ChatGPT"
    for label in ("ChatGPT", "Claude", "Gemini"):
        assert label in report.answer


def test_second_round_adds_revisions() -> None:
    council = build(config=CouncilConfig(rounds=2))
    report = council.deliberate_sync(QUESTION)
    assert [item.round for item in report.contributions] == [1, 1, 1, 2, 2, 2]
    finals = report.final_by_member()
    assert set(finals) == {"ChatGPT", "Claude", "Gemini"}
    assert all(item.round == 2 for item in finals.values())


def test_anonymisation_hides_other_labels() -> None:
    providers = {label: MockProvider(model=label) for label in ("ChatGPT", "Claude", "Gemini")}
    members = [Member(label=label, provider=provider) for label, provider in providers.items()]
    council = Council(members, config=CouncilConfig(rounds=2))
    council.deliberate_sync(QUESTION)

    prompts = [call for calls in providers["Claude"].calls for call in calls]
    rebuttal = [message.content for message in prompts if "REPONSES ANONYMES" in message.content]
    assert rebuttal, "le tour 2 doit fournir les reponses anonymisees"
    section = rebuttal[-1].split("[[REPONSES ANONYMES]]")[1]
    assert "### A" in section
    assert "ChatGPT" not in section and "Gemini" not in section


def test_personas_are_injected() -> None:
    provider = MockProvider()
    member = Member(label="Claude", provider=provider, persona="risques et cas limites")
    Council([member], config=CouncilConfig(rounds=1)).deliberate_sync(QUESTION)
    system = provider.calls[0][0].content
    assert "risques et cas limites" in system


def test_members_run_in_parallel() -> None:
    council = build(
        mock_members("A", "B", "C", delay=0.1),
        config=CouncilConfig(rounds=1, concurrency=3),
    )
    started = time.perf_counter()
    council.deliberate_sync(QUESTION)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.28, f"les membres ne semblent pas paralleles: {elapsed:.2f}s"


def test_single_member_council() -> None:
    council = Council([Member(label="Solo", provider=MockProvider())])
    report = council.deliberate_sync(QUESTION)
    assert report.status == "succeeded"
    assert report.judge == "Solo"


# ------------------------------------------------------------------ pannes
def test_member_failure_is_partial_not_fatal() -> None:
    members = [
        Member(label="OK", provider=MockProvider()),
        Member(label="KO", provider=ScriptedProvider(script=[ProviderError("panne")])),
        Member(label="KO2", provider=ScriptedProvider(script=[ProviderError("panne")])),
    ]
    council = Council(members, config=CouncilConfig(rounds=1))
    report = council.deliberate_sync(QUESTION)
    assert report.status == "partial"
    assert any("KO" in error for error in report.errors)
    assert report.answer
    assert "OK" in report.answer


def test_all_members_failing_gives_failed_status() -> None:
    members = [
        Member(label="A", provider=ScriptedProvider(script=[ProviderError("panne")])),
        Member(label="B", provider=ScriptedProvider(script=[ProviderError("panne")])),
    ]
    report = Council(members, config=CouncilConfig(rounds=1)).deliberate_sync(QUESTION)
    assert report.status == "failed"
    assert "aucun membre" in report.answer.lower()


def test_empty_member_response_is_a_failure() -> None:
    members = [
        Member(label="Vide", provider=ScriptedProvider(script=[LLMResponse(text="")])),
        Member(label="Plein", provider=MockProvider()),
    ]
    report = Council(members, config=CouncilConfig(rounds=1)).deliberate_sync(QUESTION)
    assert report.status == "partial"
    assert any("vide" in error for error in report.errors)


def test_judge_failure_falls_back_to_raw_contributions() -> None:
    members = mock_members("ChatGPT", "Claude")
    judge = Member(label="Juge", provider=ScriptedProvider(script=[ProviderError("panne")]))
    report = Council(members, judge=judge, config=CouncilConfig(rounds=1)).deliberate_sync(QUESTION)
    assert "contributions brutes" in report.answer
    assert "ChatGPT" in report.answer


def test_member_timeout_is_reported() -> None:
    members = [
        Member(label="Lent", provider=MockProvider(delay_s=0.2)),
        Member(label="Rapide", provider=MockProvider()),
    ]
    council = Council(members, config=CouncilConfig(rounds=1, member_timeout_s=0.05))
    report = council.deliberate_sync(QUESTION)
    assert report.status == "partial"
    assert any("timeout" in error for error in report.errors)


def test_budget_exhaustion_is_reported() -> None:
    council = build(
        config=CouncilConfig(rounds=2),
        budget=Budget(max_llm_calls=1, max_tokens=10_000, max_seconds=60),
    )
    report = council.deliberate_sync(QUESTION)
    assert report.status in {"partial", "failed"}
    assert any("budget" in error for error in report.errors)


# -------------------------------------------------------------- validation
def test_empty_council_rejected() -> None:
    with pytest.raises(AgentError, match="au moins un membre"):
        Council([])


def test_duplicate_labels_rejected() -> None:
    members = mock_members("A", "B")
    with pytest.raises(AgentError, match="dupliquees"):
        Council([members[0], Member(label="A", provider=MockProvider())])


def test_empty_question_rejected() -> None:
    with pytest.raises(AgentError, match="vide"):
        build().deliberate_sync("   ")


def test_too_long_question_rejected() -> None:
    with pytest.raises(AgentError, match="trop longue"):
        build().deliberate_sync("a" * 2001)


@pytest.mark.parametrize("kwargs", [{"rounds": 0}, {"concurrency": 0}, {"member_timeout_s": 0}])
def test_config_validation(kwargs) -> None:
    with pytest.raises(ValueError):
        CouncilConfig(**kwargs)


# -------------------------------------------------------------- rapport/IO
def test_report_is_json_serializable() -> None:
    report = build(config=CouncilConfig(rounds=2)).deliberate_sync(QUESTION)
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
    assert payload["status"] == "succeeded"
    assert payload["usage"]["llm_calls"] >= 6  # 3 membres x 2 tours + juge
    assert payload["judge"] == "ChatGPT"


def test_events_are_emitted() -> None:
    sink = CollectorSink()
    council = build(config=CouncilConfig(rounds=2), bus=EventBus([sink], run_id="council-test"))
    council.deliberate_sync(QUESTION)
    kinds = sink.kinds()
    assert kinds[0] == "council.start"
    assert kinds[-1] == "council.end"
    assert kinds.count("council.member.end") == 6
    assert "council.judge.start" in kinds


def test_contribution_helper() -> None:
    contribution = Contribution(label="A", round=2, text="texte")
    payload = contribution.to_dict()
    assert payload["label"] == "A"
    assert payload["round"] == 2
    assert payload["ok"] is True
    assert "usage" in payload
