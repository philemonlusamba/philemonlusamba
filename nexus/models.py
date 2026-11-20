"""Modeles de donnees et validation de Nexus HLP.AI."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from nexus.catalog import ENGINE_BY_ID

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4"}
RESOLUTIONS = {"480p", "720p", "1080p"}
CONNECTORS = {"auto", "demo", "replicate", "fal", "webhook"}
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ValidationError(ValueError):
    """La requete client ne respecte pas le contrat public."""


@dataclass(frozen=True, slots=True)
class VideoRequest:
    """Demande normalisee, independante de l'API fournisseur."""

    prompt: str
    engine: str
    connector: str = "auto"
    model_ref: str = ""
    negative_prompt: str = ""
    image_url: str = ""
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration: int = 5
    seed: int | None = None
    style: str = "cinematic"
    generate_audio: bool = False

    @classmethod
    def from_payload(cls, payload: Any) -> VideoRequest:
        if not isinstance(payload, dict):
            raise ValidationError("un objet JSON est attendu")

        prompt = _clean(payload.get("prompt"), "prompt", maximum=2000)
        if len(prompt) < 3:
            raise ValidationError("le prompt doit contenir au moins 3 caracteres")

        engine = _clean(payload.get("engine", "sora"), "engine", maximum=60).lower()
        if engine not in ENGINE_BY_ID:
            raise ValidationError(f"moteur inconnu: {engine}")

        connector = _clean(payload.get("connector", "auto"), "connector", maximum=30).lower()
        if connector not in CONNECTORS:
            raise ValidationError(f"connecteur inconnu: {connector}")

        ratio = _clean(payload.get("aspect_ratio", "16:9"), "aspect_ratio", maximum=8)
        if ratio not in RATIOS:
            raise ValidationError(f"format non accepte: {ratio}")

        resolution = _clean(payload.get("resolution", "720p"), "resolution", maximum=8)
        if resolution not in RESOLUTIONS:
            raise ValidationError(f"resolution non acceptee: {resolution}")

        try:
            duration = int(payload.get("duration", 5))
        except (TypeError, ValueError) as exc:
            raise ValidationError("duration doit etre un nombre entier") from exc
        if duration < 1 or duration > 60:
            raise ValidationError("duration doit etre comprise entre 1 et 60 secondes")

        raw_seed = payload.get("seed")
        seed: int | None = None
        if raw_seed not in {None, ""}:
            try:
                seed = int(raw_seed)
            except (TypeError, ValueError) as exc:
                raise ValidationError("seed doit etre un entier") from exc
            if seed < 0 or seed > 2**32 - 1:
                raise ValidationError("seed doit etre compris entre 0 et 4294967295")

        image_url = _clean(payload.get("image_url", ""), "image_url", maximum=4000, required=False)
        if image_url and not image_url.startswith(("https://", "http://")):
            raise ValidationError("image_url doit commencer par https:// ou http://")

        return cls(
            prompt=prompt,
            engine=engine,
            connector=connector,
            model_ref=_clean(
                payload.get("model_ref", ""), "model_ref", maximum=240, required=False
            ),
            negative_prompt=_clean(
                payload.get("negative_prompt", ""),
                "negative_prompt",
                maximum=1000,
                required=False,
            ),
            image_url=image_url,
            aspect_ratio=ratio,
            resolution=resolution,
            duration=duration,
            seed=seed,
            style=_clean(payload.get("style", "cinematic"), "style", maximum=60),
            generate_audio=bool(payload.get("generate_audio", False)),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class VideoJob:
    """Etat persiste d'une generation."""

    id: str
    request: VideoRequest
    connector: str
    status: JobStatus = "queued"
    progress: int = 0
    stage: str = "Dans la file"
    result_url: str = ""
    poster_url: str = ""
    external_id: str = ""
    error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    demo: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "request": self.request.to_dict(),
            "connector": self.connector,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "result_url": self.result_url,
            "poster_url": self.poster_url,
            "external_id": self.external_id,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "demo": self.demo,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoJob:
        request = VideoRequest(**data["request"])
        allowed = {
            "id",
            "connector",
            "status",
            "progress",
            "stage",
            "result_url",
            "poster_url",
            "external_id",
            "error",
            "created_at",
            "updated_at",
            "demo",
            "metadata",
        }
        values = {key: value for key, value in data.items() if key in allowed}
        return cls(request=request, **values)


def _clean(value: object, name: str, *, maximum: int, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{name} doit etre une chaine")
    cleaned = " ".join(value.split())
    if required and not cleaned:
        raise ValidationError(f"{name} est obligatoire")
    if len(cleaned) > maximum:
        raise ValidationError(f"{name} depasse {maximum} caracteres")
    return cleaned
