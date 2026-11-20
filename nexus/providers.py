"""Connecteurs de generation video pour Nexus HLP.AI.

Trois routes sont implementees : Replicate, fal.ai et un webhook normalise.
Elles couvrent de nombreux modeles sans embarquer les secrets dans le
navigateur. Les APIs commerciales natives (Sora, Veo, Runway, etc.) evoluent
independamment : elles peuvent etre placees derriere le webhook ou ajoutees
comme plugin sans changer l'interface.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from nexus.models import VideoRequest

ProgressCallback = Callable[[int, str, str], None]
CancelledCallback = Callable[[], bool]
MODEL_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,238}[A-Za-z0-9]$")


class GenerationError(RuntimeError):
    """Echec explicite d'un fournisseur video."""


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Resultat final d'une passerelle."""

    url: str
    external_id: str = ""
    metadata: dict[str, Any] | None = None


class VideoProvider(Protocol):
    """Contrat commun aux passerelles asynchrones."""

    id: str

    def generate(
        self,
        request: VideoRequest,
        update: ProgressCallback,
        cancelled: CancelledCallback,
    ) -> ProviderResult: ...


class ReplicateProvider:
    """Passerelle vers ``owner/model`` sur l'API Predictions de Replicate."""

    id = "replicate"

    def __init__(self, token: str, *, timeout_s: int = 900) -> None:
        if not token:
            raise GenerationError("REPLICATE_API_TOKEN absente")
        self.token = token
        self.timeout_s = timeout_s
        self.base_url = os.environ.get("REPLICATE_BASE_URL", "https://api.replicate.com/v1").rstrip(
            "/"
        )

    def generate(
        self,
        request: VideoRequest,
        update: ProgressCallback,
        cancelled: CancelledCallback,
    ) -> ProviderResult:
        model = _validated_model_ref(request.model_ref, "Replicate", "owner/model")
        model_path = urllib.parse.quote(model, safe="/-_.")
        update(5, "Envoi a Replicate", "")
        prediction = _request_json(
            "POST",
            f"{self.base_url}/models/{model_path}/predictions",
            {"input": _gateway_input(request)},
            {
                "Authorization": f"Bearer {self.token}",
                "Prefer": "wait=5",
            },
        )
        external_id = str(prediction.get("id", ""))
        started = time.monotonic()
        while True:
            if cancelled():
                raise GenerationError("generation annulee")
            status = str(prediction.get("status", "")).lower()
            if status == "succeeded":
                url = _extract_media_url(prediction.get("output"))
                if not url:
                    raise GenerationError("Replicate a termine sans URL video")
                return ProviderResult(
                    url=url, external_id=external_id, metadata={"raw": prediction}
                )
            if status in {"failed", "canceled", "cancelled"}:
                detail = prediction.get("error") or f"statut {status}"
                raise GenerationError(f"Replicate: {detail}")
            if time.monotonic() - started > self.timeout_s:
                raise GenerationError("timeout Replicate")
            elapsed = time.monotonic() - started
            progress = min(92, 15 + int(elapsed / max(self.timeout_s, 1) * 77))
            update(progress, "Rendu Replicate", external_id)
            time.sleep(3)
            get_url = _nested(prediction, "urls", "get")
            if not get_url and external_id:
                get_url = f"{self.base_url}/predictions/{external_id}"
            if not get_url:
                raise GenerationError("Replicate n'a fourni aucun URL de suivi")
            prediction = _request_json(
                "GET", str(get_url), None, {"Authorization": f"Bearer {self.token}"}
            )


class FalProvider:
    """Passerelle vers un endpoint de file fal.ai."""

    id = "fal"

    def __init__(self, key: str, *, timeout_s: int = 900) -> None:
        if not key:
            raise GenerationError("FAL_KEY absente")
        self.key = key
        self.timeout_s = timeout_s
        self.base_url = os.environ.get("FAL_QUEUE_URL", "https://queue.fal.run").rstrip("/")

    def generate(
        self,
        request: VideoRequest,
        update: ProgressCallback,
        cancelled: CancelledCallback,
    ) -> ProviderResult:
        model = _validated_model_ref(request.model_ref, "fal.ai", "fal-ai/nom-du-modele")
        model_path = urllib.parse.quote(model, safe="/-_.")
        update(5, "Ajout a la file fal.ai", "")
        response = _request_json(
            "POST",
            f"{self.base_url}/{model_path}",
            _gateway_input(request),
            {"Authorization": f"Key {self.key}"},
        )
        request_id = str(response.get("request_id", ""))
        direct = _extract_media_url(response)
        if direct and not response.get("status_url"):
            return ProviderResult(url=direct, external_id=request_id, metadata={"raw": response})

        status_url = response.get("status_url")
        result_url = response.get("response_url")
        if not status_url:
            if not request_id:
                raise GenerationError("fal.ai n'a fourni ni resultat ni identifiant")
            status_url = f"{self.base_url}/{model_path}/requests/{request_id}/status"
            result_url = f"{self.base_url}/{model_path}/requests/{request_id}"

        started = time.monotonic()
        while True:
            if cancelled():
                raise GenerationError("generation annulee")
            if time.monotonic() - started > self.timeout_s:
                raise GenerationError("timeout fal.ai")
            status_payload = _request_json(
                "GET", str(status_url), None, {"Authorization": f"Key {self.key}"}
            )
            status = str(status_payload.get("status", "")).upper()
            if status in {"COMPLETED", "SUCCEEDED"}:
                final = _request_json(
                    "GET", str(result_url), None, {"Authorization": f"Key {self.key}"}
                )
                url = _extract_media_url(final)
                if not url:
                    raise GenerationError("fal.ai a termine sans URL video")
                return ProviderResult(url=url, external_id=request_id, metadata={"raw": final})
            if status in {"FAILED", "CANCELLED", "CANCELED"}:
                detail = status_payload.get("error") or f"statut {status}"
                raise GenerationError(f"fal.ai: {detail}")
            elapsed = time.monotonic() - started
            progress = min(92, 12 + int(elapsed / max(self.timeout_s, 1) * 80))
            update(progress, "Rendu fal.ai", request_id)
            time.sleep(3)


class WebhookProvider:
    """Pont vers une API privee respectant le contrat Nexus.

    Reponse immediate acceptee : ``{"video_url": "https://..."}``.
    Reponse asynchrone acceptee : ``{"id": "...", "status_url": "..."}``,
    puis un GET renvoyant ``status`` et enfin ``video_url``/``output``.
    """

    id = "webhook"

    def __init__(self, url: str, token: str = "", *, timeout_s: int = 900) -> None:
        if not url.startswith(("https://", "http://")):
            raise GenerationError("NEXUS_WEBHOOK_URL invalide")
        self.url = url
        self.token = token
        self.timeout_s = timeout_s

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def generate(
        self,
        request: VideoRequest,
        update: ProgressCallback,
        cancelled: CancelledCallback,
    ) -> ProviderResult:
        update(5, "Envoi au webhook", "")
        response = _request_json(
            "POST",
            self.url,
            {"type": "video.generate", "request": request.to_dict()},
            self.headers,
        )
        external_id = str(response.get("id") or response.get("job_id") or "")
        direct = _extract_media_url(response)
        status_url = response.get("status_url")
        if direct and not status_url:
            return ProviderResult(url=direct, external_id=external_id, metadata={"raw": response})
        if not status_url:
            raise GenerationError("le webhook n'a fourni ni video_url ni status_url")

        started = time.monotonic()
        while True:
            if cancelled():
                raise GenerationError("generation annulee")
            if time.monotonic() - started > self.timeout_s:
                raise GenerationError("timeout webhook")
            current = _request_json("GET", str(status_url), None, self.headers)
            status = str(current.get("status", "")).lower()
            reported = current.get("progress")
            if isinstance(reported, (int, float)):
                progress = max(5, min(95, int(reported)))
            else:
                elapsed = time.monotonic() - started
                progress = min(92, 12 + int(elapsed / max(self.timeout_s, 1) * 80))
            update(progress, str(current.get("stage") or "Rendu externe"), external_id)
            if status in {"completed", "succeeded", "success", "done"}:
                url = _extract_media_url(current)
                if not url and current.get("result_url"):
                    result = _request_json("GET", str(current["result_url"]), None, self.headers)
                    url = _extract_media_url(result)
                if not url:
                    raise GenerationError("le webhook a termine sans URL video")
                return ProviderResult(url=url, external_id=external_id, metadata={"raw": current})
            if status in {"failed", "cancelled", "canceled", "error"}:
                raise GenerationError(str(current.get("error") or f"statut {status}"))
            time.sleep(3)


def build_provider(connector: str, env: dict[str, str] | None = None) -> VideoProvider:
    """Instancie uniquement un connecteur configure cote serveur."""
    environ = os.environ if env is None else env
    if connector == "replicate":
        return ReplicateProvider(environ.get("REPLICATE_API_TOKEN", ""))
    if connector == "fal":
        return FalProvider(environ.get("FAL_KEY", ""))
    if connector == "webhook":
        return WebhookProvider(
            environ.get("NEXUS_WEBHOOK_URL", ""), environ.get("NEXUS_WEBHOOK_TOKEN", "")
        )
    raise GenerationError(f"connecteur non executable: {connector}")


def resolve_connector(requested: str, env: dict[str, str] | None = None) -> str:
    """Route automatique : passerelle configuree, sinon demo explicite."""
    environ = os.environ if env is None else env
    if requested != "auto":
        return requested
    if environ.get("REPLICATE_API_TOKEN"):
        return "replicate"
    if environ.get("FAL_KEY"):
        return "fal"
    if environ.get("NEXUS_WEBHOOK_URL"):
        return "webhook"
    return "demo"


def _gateway_input(request: VideoRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": request.prompt,
        "aspect_ratio": request.aspect_ratio,
        "duration": request.duration,
        "resolution": request.resolution,
    }
    if request.negative_prompt:
        payload["negative_prompt"] = request.negative_prompt
    if request.image_url:
        payload["image"] = request.image_url
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.generate_audio:
        payload["generate_audio"] = True
    return payload


def _validated_model_ref(value: str, provider: str, example: str) -> str:
    if not value:
        raise GenerationError(f"model_ref requis pour {provider} (exemple: {example})")
    if ".." in value or not MODEL_REF_RE.fullmatch(value):
        raise GenerationError("model_ref contient des caracteres non autorises")
    return value


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    *,
    timeout_s: int = 90,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise GenerationError(f"HTTP {exc.code} depuis le fournisseur: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GenerationError(f"fournisseur injoignable: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenerationError("le fournisseur n'a pas renvoye de JSON valide") from exc
    if not isinstance(parsed, dict):
        raise GenerationError("la reponse fournisseur doit etre un objet JSON")
    return parsed


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_media_url(value: Any, *, depth: int = 0) -> str:
    """Extrait prudemment une URL video dans les formes usuelles d'API."""
    if depth > 7:
        return ""
    if isinstance(value, str):
        return value if value.startswith(("https://", "http://")) else ""
    if isinstance(value, list):
        for item in value:
            found = _extract_media_url(item, depth=depth + 1)
            if found:
                return found
        return ""
    if not isinstance(value, dict):
        return ""
    preferred = (
        "video_url",
        "video",
        "media_url",
        "download_url",
        "output",
        "file",
        "url",
    )
    for key in preferred:
        if key in value:
            found = _extract_media_url(value[key], depth=depth + 1)
            if found:
                return found
    for key, item in value.items():
        if key in {"status_url", "response_url", "result_url", "logs", "web"}:
            continue
        found = _extract_media_url(item, depth=depth + 1)
        if found:
            return found
    return ""
