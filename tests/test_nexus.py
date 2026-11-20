"""Tests hors ligne de Nexus HLP.AI : validation, file et API HTTP."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import nexus.jobs as jobs_module
import pytest
from nexus.catalog import ENGINE_BY_ID, connector_states, public_catalog
from nexus.jobs import JobStore, preview_svg
from nexus.models import ValidationError, VideoRequest
from nexus.providers import (
    GenerationError,
    _extract_media_url,
    _validated_model_ref,
    build_provider,
    resolve_connector,
)
from nexus.server import build_server


def request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt": "Kinshasa futuriste sous une pluie neon",
        "engine": "sora",
        "connector": "demo",
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "duration": 5,
        "style": "cinematic",
    }
    payload.update(overrides)
    return payload


def test_catalog_contains_major_commercial_and_open_engines() -> None:
    expected = {
        "sora",
        "veo",
        "runway",
        "kling",
        "luma",
        "pika",
        "hailuo",
        "firefly",
        "seedance",
        "stable-video",
        "wan",
        "hunyuan",
        "cogvideox",
        "mochi",
        "comfyui",
    }
    assert expected <= set(ENGINE_BY_ID)
    assert len(ENGINE_BY_ID) >= 15
    assert {item.integration for item in ENGINE_BY_ID.values()} >= {"commercial", "open", "local"}


def test_public_catalog_exposes_state_but_never_secret() -> None:
    secret = "r8_secret_ne_doit_pas_sortir"
    catalog = public_catalog({"REPLICATE_API_TOKEN": secret})
    encoded = json.dumps(catalog)
    assert secret not in encoded
    replicate = next(item for item in catalog["connectors"] if item["id"] == "replicate")
    assert replicate["configured"] is True
    assert replicate["key_env"] == "REPLICATE_API_TOKEN"


def test_connector_states_demo_is_always_ready() -> None:
    states = connector_states({})
    assert states[0].id == "demo"
    assert states[0].configured is True
    assert all(not state.configured for state in states[1:])


def test_video_request_normalises_values() -> None:
    request = VideoRequest.from_payload(
        request_payload(prompt="  Une   scene   lente  ", seed="42", generate_audio=1)
    )
    assert request.prompt == "Une scene lente"
    assert request.seed == 42
    assert request.generate_audio is True


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"prompt": ""}, "prompt"),
        ({"prompt": "ok"}, "au moins 3"),
        ({"engine": "inconnu"}, "moteur inconnu"),
        ({"connector": "magique"}, "connecteur inconnu"),
        ({"aspect_ratio": "21:9"}, "format non accepte"),
        ({"resolution": "4k"}, "resolution non acceptee"),
        ({"duration": 0}, "entre 1 et 60"),
        ({"duration": "abc"}, "nombre entier"),
        ({"seed": -1}, "seed doit etre compris"),
        ({"image_url": "file:///etc/passwd"}, "image_url"),
    ],
)
def test_video_request_rejects_invalid_input(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        VideoRequest.from_payload(request_payload(**changes))


def test_connector_resolution_is_explicit() -> None:
    assert resolve_connector("auto", {}) == "demo"
    assert resolve_connector("auto", {"FAL_KEY": "secret"}) == "fal"
    assert resolve_connector("replicate", {}) == "replicate"
    with pytest.raises(GenerationError, match="REPLICATE_API_TOKEN"):
        build_provider("replicate", {})


def test_model_reference_validation() -> None:
    assert _validated_model_ref("owner/model-v2", "test", "owner/model") == "owner/model-v2"
    with pytest.raises(GenerationError, match="requis"):
        _validated_model_ref("", "test", "owner/model")
    with pytest.raises(GenerationError, match="non autorises"):
        _validated_model_ref("../secret", "test", "owner/model")


def test_media_url_extraction_handles_common_shapes() -> None:
    assert _extract_media_url({"output": ["https://cdn.example/video.mp4"]}).endswith(".mp4")
    assert _extract_media_url({"video": {"url": "https://cdn.example/out.webm"}}).endswith(".webm")
    assert _extract_media_url({"status_url": "https://api.example/job"}) == ""


def test_demo_job_progress_and_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000.0]
    monkeypatch.setattr(jobs_module.time, "time", lambda: clock[0])
    path = tmp_path / "jobs.json"
    store = JobStore(path, env={}, demo_duration_s=8)
    job = store.submit(VideoRequest.from_payload(request_payload()))
    assert job.status == "queued"
    assert job.demo is True
    assert path.is_file()

    clock[0] += 9
    completed = store.get(job.id)
    assert completed.status == "completed"
    assert completed.progress == 100
    assert completed.result_url.endswith("preview.svg")

    restored = JobStore(path, env={}, demo_duration_s=8).get(job.id)
    assert restored.status == "completed"
    assert restored.request.prompt.startswith("Kinshasa")


def test_auto_without_model_uses_demo_even_if_gateway_key_exists(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.json", env={"REPLICATE_API_TOKEN": "secret"})
    request = VideoRequest.from_payload(request_payload(connector="auto", model_ref=""))
    assert store.submit(request).connector == "demo"


def test_explicit_unconfigured_gateway_fails_before_job_creation(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.json", env={})
    request = VideoRequest.from_payload(
        request_payload(connector="replicate", model_ref="owner/model")
    )
    with pytest.raises(GenerationError, match="REPLICATE_API_TOKEN"):
        store.submit(request)
    assert store.list() == []


def test_preview_svg_escapes_prompt(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.json", env={})
    request = VideoRequest.from_payload(request_payload(prompt="<script>alert(1)</script> camera"))
    svg = preview_svg(store.submit(request)).decode()
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    assert "NEXUS HLP.AI" in svg


@pytest.fixture
def live_nexus(tmp_path: Path) -> Iterator[tuple[str, int]]:
    store = JobStore(tmp_path / "jobs.json", env={}, demo_duration_s=30)
    server = build_server("127.0.0.1", 0, store=store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[:2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def http_request(
    address: tuple[str, int],
    method: str,
    path: str,
    payload: dict[str, object] | bytes | None = None,
) -> tuple[int, object, dict[str, str]]:
    connection = http.client.HTTPConnection(*address, timeout=5)
    body = json.dumps(payload).encode() if isinstance(payload, dict) else payload
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    if "application/json" in response_headers.get("content-type", ""):
        content: object = json.loads(raw)
    else:
        content = raw.decode("utf-8")
    return response.status, content, response_headers


def test_http_home_health_and_catalog(live_nexus: tuple[str, int]) -> None:
    status, page, headers = http_request(live_nexus, "GET", "/")
    assert status == 200
    assert "Nexus HLP.AI" in page
    assert "content-security-policy" in headers

    status, _, _ = http_request(live_nexus, "HEAD", "/")
    assert status == 200

    status, health, _ = http_request(live_nexus, "GET", "/api/health")
    assert status == 200
    assert health["status"] == "ok"
    assert health["name"] == "Nexus HLP.AI"

    status, catalog, _ = http_request(live_nexus, "GET", "/api/catalog")
    assert status == 200
    assert len(catalog["engines"]) >= 15


def test_http_job_lifecycle(live_nexus: tuple[str, int]) -> None:
    status, created, _ = http_request(live_nexus, "POST", "/api/jobs", request_payload())
    assert status == 202
    job_id = created["job"]["id"]

    status, item, _ = http_request(live_nexus, "GET", f"/api/jobs/{job_id}")
    assert status == 200
    assert item["job"]["request"]["engine"] == "sora"

    status, svg, headers = http_request(live_nexus, "GET", f"/api/jobs/{job_id}/preview.svg")
    assert status == 200
    assert headers["content-type"].startswith("image/svg+xml")
    assert "NEXUS HLP.AI" in svg

    status, cancelled, _ = http_request(live_nexus, "POST", f"/api/jobs/{job_id}/cancel", {})
    assert status == 200
    assert cancelled["job"]["status"] == "cancelled"

    status, deleted, _ = http_request(live_nexus, "DELETE", f"/api/jobs/{job_id}")
    assert status == 200
    assert deleted["deleted"] == job_id


def test_http_rejects_bad_json_and_unknown_route(live_nexus: tuple[str, int]) -> None:
    status, error, _ = http_request(live_nexus, "POST", "/api/jobs", b"not json")
    assert status == 400
    assert error == {"error": "JSON invalide"}

    status, error, _ = http_request(live_nexus, "GET", "/api/secret")
    assert status == 404
    assert error == {"error": "route inconnue"}
