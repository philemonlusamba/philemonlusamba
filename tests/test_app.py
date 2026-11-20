"""Tests de l'application web locale du conseil."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator

import pytest
from app.server import build_server, default_app_specs, provider_states, run_council

KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_default_specs_fall_back_to_three_named_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    assert default_app_specs() == ["mock:openai", "mock:anthropic", "mock:gemini"]


def test_provider_state_never_exposes_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    secret = "sk-test-tres-secret"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    states = provider_states()
    assert states[0]["ready"] is True
    assert secret not in json.dumps(states)


def test_run_council_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    report = run_council({"question": "Index SQL ou plein texte ?", "rounds": 2})
    assert report["status"] == "succeeded"
    assert report["members"] == ["ChatGPT (mock)", "Claude (mock)", "Gemini (mock)"]
    assert len(report["contributions"]) == 6
    assert all(item["simulated"] for item in report["contributions"])
    assert "## Consensus" in report["answer"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"question": ""}, "question vide"),
        ({"question": "ok", "rounds": 3}, "rounds doit etre 1 ou 2"),
        ({"question": "x" * 2001}, "question trop longue"),
        ({"question": "ok", "models": ["mock"] * 6}, "5 membres maximum"),
    ],
)
def test_run_council_rejects_invalid_payload(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        run_council(payload)


@pytest.fixture
def live_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, int]]:
    _clear_keys(monkeypatch)
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[:2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    address: tuple[str, int],
    method: str,
    path: str,
    body: bytes | None = None,
) -> tuple[int, dict[str, object] | str]:
    connection = http.client.HTTPConnection(*address, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode("utf-8")
    content_type = response.getheader("Content-Type", "")
    connection.close()
    parsed = json.loads(raw) if "application/json" in content_type else raw
    return response.status, parsed


def test_http_health_and_home(live_app: tuple[str, int]) -> None:
    status, page = _request(live_app, "GET", "/")
    assert status == 200
    assert "ChatGPT" in page and "Claude" in page and "Gemini" in page

    status, health = _request(live_app, "GET", "/api/health")
    assert status == 200
    assert health["status"] == "ok"
    assert health["default_models"] == ["mock:openai", "mock:anthropic", "mock:gemini"]


def test_http_council_and_validation(live_app: tuple[str, int]) -> None:
    body = json.dumps({"question": "Index SQL ou plein texte ?", "rounds": 1}).encode()
    status, report = _request(live_app, "POST", "/api/council", body)
    assert status == 200
    assert report["status"] == "succeeded"
    assert len(report["contributions"]) == 3

    status, error = _request(live_app, "POST", "/api/council", b"not-json")
    assert status == 400
    assert error == {"error": "JSON invalide"}
