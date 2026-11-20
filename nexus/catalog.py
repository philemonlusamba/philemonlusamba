"""Catalogue public des familles de modeles video reunies par Nexus HLP.AI.

Le catalogue est volontairement separe des connecteurs. Une famille peut etre
visible dans l'interface sans qu'une API commerciale soit configuree. Cela
permet de ne jamais faire croire qu'une cle est presente ou qu'un service tiers
est disponible. Les identifiants de versions changent frequemment : Nexus
accepte donc un ``model_ref`` personnalisable pour les passerelles Replicate,
fal.ai et webhook.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Literal

Integration = Literal["commercial", "open", "local", "gateway"]


@dataclass(frozen=True, slots=True)
class EngineSpec:
    """Une famille de generateurs video presentee dans l'explorateur."""

    id: str
    name: str
    company: str
    description: str
    integration: Integration
    capabilities: tuple[str, ...]
    durations: tuple[int, ...]
    ratios: tuple[str, ...] = ("16:9", "9:16", "1:1")
    accent: str = "#8b5cf6"
    website: str = ""

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        data["durations"] = list(self.durations)
        data["ratios"] = list(self.ratios)
        return data


# Familles, pas promesse de disponibilite API. Les modeles et limites exactes
# sont determines par le compte du fournisseur au moment de la generation.
ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec(
        id="sora",
        name="Sora",
        company="OpenAI",
        description="Scenes cinematographiques, mouvement de camera et continuite visuelle.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "remix"),
        durations=(5, 10, 15, 20),
        accent="#22d3ee",
        website="https://openai.com/sora/",
    ),
    EngineSpec(
        id="veo",
        name="Veo",
        company="Google DeepMind",
        description="Generation haute fidelite, controle du style et narration visuelle.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "audio"),
        durations=(5, 8, 10),
        accent="#4285f4",
        website="https://deepmind.google/models/veo/",
    ),
    EngineSpec(
        id="runway",
        name="Runway Gen",
        company="Runway",
        description="Creation et transformation video pour workflows de production.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "video-to-video"),
        durations=(5, 10),
        accent="#f1f5f9",
        website="https://runwayml.com/",
    ),
    EngineSpec(
        id="kling",
        name="Kling AI",
        company="Kuaishou",
        description="Mouvement realiste, physique et generation de plans dynamiques.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "lip-sync"),
        durations=(5, 10),
        accent="#a78bfa",
        website="https://klingai.com/",
    ),
    EngineSpec(
        id="luma",
        name="Dream Machine / Ray",
        company="Luma AI",
        description="Plans rapides, boucles, transitions et mouvements de camera controles.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "keyframes"),
        durations=(5, 9),
        accent="#fb7185",
        website="https://lumalabs.ai/dream-machine",
    ),
    EngineSpec(
        id="pika",
        name="Pika",
        company="Pika Labs",
        description="Effets creatifs, transformations d'objets et clips sociaux.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "effects"),
        durations=(3, 5, 10),
        accent="#f472b6",
        website="https://pika.art/",
    ),
    EngineSpec(
        id="hailuo",
        name="Hailuo Video",
        company="MiniMax",
        description="Generation textuelle et animation d'images avec mouvement expressif.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video"),
        durations=(6, 10),
        accent="#fb923c",
        website="https://hailuoai.video/",
    ),
    EngineSpec(
        id="firefly",
        name="Firefly Video",
        company="Adobe",
        description="Generation adaptee aux flux creatifs et outils de montage Adobe.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video", "b-roll"),
        durations=(5,),
        accent="#ef4444",
        website="https://www.adobe.com/products/firefly/features/ai-video-generator.html",
    ),
    EngineSpec(
        id="seedance",
        name="Seedance",
        company="ByteDance",
        description="Clips narratifs, mouvements multi-plans et styles varies.",
        integration="commercial",
        capabilities=("text-to-video", "image-to-video"),
        durations=(5, 10),
        accent="#38bdf8",
        website="https://seed.bytedance.com/",
    ),
    EngineSpec(
        id="stable-video",
        name="Stable Video",
        company="Stability AI",
        description="Famille de modeles ouverts pour animation d'image et experimentation.",
        integration="open",
        capabilities=("image-to-video", "local"),
        durations=(3, 5),
        accent="#60a5fa",
        website="https://stability.ai/",
    ),
    EngineSpec(
        id="wan",
        name="Wan Video",
        company="Alibaba / Open source",
        description="Modele ouvert, deployable localement ou via une passerelle cloud.",
        integration="open",
        capabilities=("text-to-video", "image-to-video", "local"),
        durations=(5, 10),
        accent="#34d399",
        website="https://github.com/Wan-Video/Wan2.1",
    ),
    EngineSpec(
        id="hunyuan",
        name="HunyuanVideo",
        company="Tencent / Open source",
        description="Generation video ouverte pour execution GPU et personnalisation.",
        integration="open",
        capabilities=("text-to-video", "image-to-video", "local"),
        durations=(5, 10),
        accent="#10b981",
        website="https://github.com/Tencent-Hunyuan/HunyuanVideo",
    ),
    EngineSpec(
        id="cogvideox",
        name="CogVideoX",
        company="Zhipu AI / Open source",
        description="Famille ouverte pour text-to-video et image-to-video.",
        integration="open",
        capabilities=("text-to-video", "image-to-video", "local"),
        durations=(5, 10),
        accent="#2dd4bf",
        website="https://github.com/THUDM/CogVideo",
    ),
    EngineSpec(
        id="mochi",
        name="Mochi",
        company="Genmo / Open source",
        description="Modele ouvert de generation video a mouvement fluide.",
        integration="open",
        capabilities=("text-to-video", "local"),
        durations=(5, 10),
        accent="#facc15",
        website="https://github.com/genmoai/models",
    ),
    EngineSpec(
        id="comfyui",
        name="ComfyUI Video",
        company="Local / communautaire",
        description="Workflows locaux pour Wan, Hunyuan, AnimateDiff et extensions video.",
        integration="local",
        capabilities=("workflow", "text-to-video", "image-to-video", "local"),
        durations=(3, 5, 10, 15),
        accent="#94a3b8",
        website="https://github.com/comfyanonymous/ComfyUI",
    ),
)

ENGINE_BY_ID = {engine.id: engine for engine in ENGINES}


@dataclass(frozen=True, slots=True)
class ConnectorState:
    """Etat public d'une passerelle ; aucune valeur de secret n'est exposee."""

    id: str
    name: str
    description: str
    configured: bool
    key_env: str
    kind: Literal["demo", "gateway", "custom"]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def connector_states(env: dict[str, str] | None = None) -> list[ConnectorState]:
    """Retourne les connecteurs utilisables a partir des variables presentes."""
    environ = os.environ if env is None else env
    return [
        ConnectorState(
            id="demo",
            name="Nexus Demo",
            description="Apercu anime local, sans reseau, sans cle et sans cout.",
            configured=True,
            key_env="",
            kind="demo",
        ),
        ConnectorState(
            id="replicate",
            name="Replicate",
            description="Passerelle vers de nombreux modeles video commerciaux et ouverts.",
            configured=bool(environ.get("REPLICATE_API_TOKEN")),
            key_env="REPLICATE_API_TOKEN",
            kind="gateway",
        ),
        ConnectorState(
            id="fal",
            name="fal.ai",
            description="File GPU et catalogue de modeles video accessibles par API.",
            configured=bool(environ.get("FAL_KEY")),
            key_env="FAL_KEY",
            kind="gateway",
        ),
        ConnectorState(
            id="webhook",
            name="Webhook Nexus",
            description="Pont normalise vers une API privee, un proxy ou un workflow local.",
            configured=bool(environ.get("NEXUS_WEBHOOK_URL")),
            key_env="NEXUS_WEBHOOK_URL (+ NEXUS_WEBHOOK_TOKEN)",
            kind="custom",
        ),
    ]


def public_catalog(env: dict[str, str] | None = None) -> dict[str, object]:
    """Representation JSON envoyee au navigateur."""
    return {
        "engines": [engine.to_dict() for engine in ENGINES],
        "connectors": [state.to_dict() for state in connector_states(env)],
        "notice": (
            "Le catalogue recense des familles de modeles. Leur disponibilite, leurs tarifs "
            "et leurs limites dependent du fournisseur. Nexus ne contourne aucun abonnement."
        ),
    }
