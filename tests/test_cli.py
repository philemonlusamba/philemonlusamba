"""Tests de la CLI : codes de sortie stables et formats de sortie."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agents.cli import main

OBJECTIF = "Combien coutent 12 x 249,99 USD ?"


def test_tools_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tools"]) == 0
    output = capsys.readouterr().out
    assert "calc_evaluate" in output
    assert "doc_search" in output


def test_tools_command_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tools", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in payload}
    assert {"calc_evaluate", "file_read", "file_list", "text_stats"} <= names
    assert "file_write" not in names  # ecriture desactivee par defaut


def test_providers_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["providers"]) == 0
    output = capsys.readouterr().out
    assert "mock" in output and "openai" in output and "anthropic" in output


def test_plan_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan", "auditer la securite", "--offline"]) == 0
    output = capsys.readouterr().out
    assert "vague 1" in output and "t1" in output


def test_plan_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan", "auditer la securite", "--offline", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"] and payload["source"] == "fallback"


def test_run_default_is_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", OBJECTIF]) == 0
    captured = capsys.readouterr()
    assert "REPONSE FINALE" in captured.out
    assert "2999.88" in captured.out


def test_run_quiet_prints_only_answer(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", OBJECTIF, "--quiet"]) == 0
    output = capsys.readouterr().out
    assert "REPONSE FINALE" not in output
    assert "Objectif traite" in output


def test_run_writes_json_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "runs" / "rapport.json"
    assert main(["run", OBJECTIF, "--json", str(target)]) == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["usage"]["total_tokens"] > 0
    assert "results" in payload
    capsys.readouterr()


def test_run_json_to_stdout_is_pure_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", OBJECTIF, "--json", "-"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["objective"] == OBJECTIF


def test_run_writes_trace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trace = tmp_path / "trace.jsonl"
    assert main(["run", OBJECTIF, "--trace", str(trace), "--quiet"]) == 0
    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "run.start"
    assert any(event["event"] == "task.start" for event in lines)
    capsys.readouterr()


def test_run_returns_failure_code_on_budget(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", OBJECTIF, "--max-llm-calls", "1", "--quiet"]) == 1
    capsys.readouterr()


def test_run_with_unknown_provider_returns_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "objectif", "--provider", "mistral"]) == 2
    assert "provider inconnu" in capsys.readouterr().err


def test_missing_key_is_a_usage_error(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["run", "objectif", "--provider", "openai"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_invalid_concurrency_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "objectif", "--concurrency", "0"]) == 2
    assert "argument invalide" in capsys.readouterr().err


def test_objective_is_required() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run"])
    assert excinfo.value.code == 2


def test_version_flag() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


# ------------------------------------------------------------------ conseil
def test_council_defaults_to_three_mock_seats(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["council", "Faut-il un index SQL ou une recherche plein texte ?"]) == 0
    output = capsys.readouterr().out
    assert "ChatGPT (mock)" in output
    assert "Claude (mock)" in output
    assert "Gemini (mock)" in output
    assert "REPONSE FINALE" in output


def test_council_single_round_has_no_revisions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["council", "question ?", "--rounds", "1"]) == 0
    output = capsys.readouterr().out
    assert "tour 1" in output
    assert "tour 2" not in output


def test_council_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["council", "question ?", "--json", "-"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["members"]) == 3
    assert payload["status"] == "succeeded"
    assert payload["contributions"]


def test_council_writes_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "conseil.json"
    assert main(["council", "question ?", "--json", str(target), "--quiet"]) == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["judge"] == "ChatGPT (mock)"
    capsys.readouterr()


def test_council_quiet_prints_only_answer(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["council", "question ?", "--quiet"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("## Consensus")


def test_council_unknown_model_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["council", "question ?", "--models", "mistral"]) == 2
    assert "provider inconnu" in capsys.readouterr().err


def test_council_explicit_models(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["council", "question ?", "--models", "mock:a,mock:b"]) == 0
    output = capsys.readouterr().out
    assert "conseil OK" in output


def test_council_labels_are_unique_and_branded() -> None:
    from agents.cli import council_label

    used: set[str] = set()
    assert council_label("mock:openai", used) == "ChatGPT (mock)"
    assert council_label("mock:openai", used) == "ChatGPT (mock) #2"
    assert council_label("anthropic", used) == "Claude"
    assert council_label("gemini:gemini-2.0-flash", used) == "Gemini"


def test_default_council_specs_autodetect_keys(monkeypatch) -> None:
    from agents.cli import default_council_specs

    assert default_council_specs({}) == ["mock:openai", "mock:anthropic", "mock:gemini"]
    specs = default_council_specs({"OPENAI_API_KEY": "sk-x"})
    assert specs[0] == "openai"
    assert len(specs) == 3
    assert default_council_specs({"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k"})[:2] == [
        "openai",
        "anthropic",
    ]
    full = default_council_specs(
        {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GEMINI_API_KEY": "k"}
    )
    assert full == ["openai", "anthropic", "gemini"]
