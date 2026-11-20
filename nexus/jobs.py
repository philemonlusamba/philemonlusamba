"""File de generations, persistance locale et apercu de demonstration."""

# Les lignes longues restantes sont le balisage SVG lisible de l'apercu anime.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import html
import json
import os
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

from nexus.models import VideoJob, VideoRequest
from nexus.providers import GenerationError, build_provider, resolve_connector

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class JobNotFound(KeyError):
    """Identifiant de generation absent."""


class JobStore:
    """Stockage thread-safe ; les secrets ne sont jamais serialises."""

    def __init__(
        self,
        path: str | Path = "runs/nexus_jobs.json",
        *,
        env: dict[str, str] | None = None,
        demo_duration_s: float = 8.0,
    ) -> None:
        self.path = Path(path)
        self.env = dict(os.environ if env is None else env)
        self.demo_duration_s = max(0.2, demo_duration_s)
        self._lock = threading.RLock()
        self._jobs: dict[str, VideoJob] = {}
        self._cancelled: set[str] = set()
        self._load()

    # ---------------------------------------------------------------- API
    def submit(self, request: VideoRequest) -> VideoJob:
        connector = resolve_connector(request.connector, self.env)
        if request.connector == "auto" and connector != "demo" and not request.model_ref:
            configured_default = self.env.get(f"NEXUS_{connector.upper()}_MODEL", "")
            if configured_default:
                request = replace(request, model_ref=configured_default)
            else:
                # Auto ne doit jamais consommer une API avec un modele implicite ou invalide.
                connector = "demo"

        if connector != "demo":
            # Echec de configuration renvoye avant de creer un faux job en file.
            build_provider(connector, self.env)
            if not request.model_ref and connector in {"replicate", "fal"}:
                raise GenerationError(
                    f"model_ref requis pour {connector}; renseignez-le dans les reglages avances"
                )

        now = time.time()
        job_id = uuid.uuid4().hex[:12]
        job = VideoJob(
            id=job_id,
            request=request,
            connector=connector,
            status="queued",
            progress=2,
            stage="Dans la file Nexus",
            poster_url=f"/api/jobs/{job_id}/preview.svg",
            created_at=now,
            updated_at=now,
            demo=connector == "demo",
        )
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
            self._save()

        if connector != "demo":
            thread = threading.Thread(
                target=self._run_external,
                args=(job.id,),
                name=f"nexus-{job.id}",
                daemon=True,
            )
            thread.start()
        return self.get(job.id)

    def get(self, job_id: str) -> VideoJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            changed = self._refresh_demo(job)
            if changed:
                self._save()
            return VideoJob.from_dict(job.to_dict())

    def list(self, *, limit: int = 50) -> list[VideoJob]:
        limit = max(1, min(100, limit))
        with self._lock:
            changed = False
            for job in self._jobs.values():
                changed = self._refresh_demo(job) or changed
            if changed:
                self._save()
            ordered = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [VideoJob.from_dict(job.to_dict()) for job in ordered[:limit]]

    def cancel(self, job_id: str) -> VideoJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.status not in TERMINAL_STATUSES:
                self._cancelled.add(job.id)
                job.status = "cancelled"
                job.stage = "Annulee"
                job.updated_at = time.time()
                self._save()
            return VideoJob.from_dict(job.to_dict())

    def delete(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.status not in TERMINAL_STATUSES:
                raise GenerationError("annulez la generation avant de la supprimer")
            del self._jobs[job_id]
            self._cancelled.discard(job_id)
            self._save()

    def stats(self) -> dict[str, int]:
        jobs = self.list(limit=100)
        return {
            "total": len(jobs),
            "active": sum(job.status in {"queued", "running"} for job in jobs),
            "completed": sum(job.status == "completed" for job in jobs),
            "failed": sum(job.status == "failed" for job in jobs),
        }

    # ------------------------------------------------------------ workers
    def _run_external(self, job_id: str) -> None:
        try:
            with self._lock:
                job = self._jobs[job_id]
                request = job.request
                connector = job.connector
                job.status = "running"
                job.stage = "Initialisation du fournisseur"
                job.progress = 4
                job.updated_at = time.time()
                self._save()
            provider = build_provider(connector, self.env)

            def update(progress: int, stage: str, external_id: str) -> None:
                with self._lock:
                    current = self._jobs.get(job_id)
                    if current is None or current.status == "cancelled":
                        return
                    current.status = "running"
                    current.progress = max(current.progress, min(95, progress))
                    current.stage = stage[:120]
                    if external_id:
                        current.external_id = external_id[:240]
                    current.updated_at = time.time()
                    self._save()

            result = provider.generate(
                request,
                update,
                lambda: job_id in self._cancelled,
            )
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None or current.status == "cancelled":
                    return
                current.status = "completed"
                current.progress = 100
                current.stage = "Video terminee"
                current.result_url = result.url
                current.external_id = result.external_id[:240]
                current.metadata = {"provider": connector}
                current.updated_at = time.time()
                self._save()
        except Exception as exc:  # une panne fournisseur ne doit pas tuer le serveur
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None or current.status == "cancelled":
                    return
                current.status = "failed"
                current.stage = "Echec"
                current.error = f"{type(exc).__name__}: {exc}"[:600]
                current.updated_at = time.time()
                self._save()

    # ---------------------------------------------------------- demo/persist
    def _refresh_demo(self, job: VideoJob) -> bool:
        if not job.demo or job.status in TERMINAL_STATUSES:
            return False
        elapsed = max(0.0, time.time() - job.created_at)
        ratio = elapsed / self.demo_duration_s
        previous = (job.status, job.progress, job.stage)
        if ratio < 0.08:
            job.status, job.progress, job.stage = "queued", 3, "Dans la file Nexus"
        elif ratio < 0.28:
            job.status = "running"
            job.progress = 10 + int((ratio - 0.08) / 0.20 * 20)
            job.stage = "Analyse du prompt"
        elif ratio < 0.72:
            job.status = "running"
            job.progress = 30 + int((ratio - 0.28) / 0.44 * 48)
            job.stage = "Synthese des plans"
        elif ratio < 1:
            job.status = "running"
            job.progress = 78 + int((ratio - 0.72) / 0.28 * 21)
            job.stage = "Interpolation et encodage"
        else:
            job.status = "completed"
            job.progress = 100
            job.stage = "Apercu demo termine"
            job.result_url = job.poster_url
            job.metadata = {"mode": "demo", "export": "webm-dans-le-navigateur"}
        current = (job.status, job.progress, job.stage)
        if current != previous:
            job.updated_at = time.time()
            return True
        return False

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            items = payload.get("jobs", []) if isinstance(payload, dict) else []
            for item in items:
                job = VideoJob.from_dict(item)
                if job.status in {"queued", "running"} and not job.demo:
                    job.status = "failed"
                    job.stage = "Interrompue par le redemarrage"
                    job.error = "le serveur a redemarre pendant une generation externe"
                self._jobs[job.id] = job
        except (OSError, ValueError, TypeError, KeyError):
            # Un historique corrompu ne doit pas empecher le demarrage.
            self._jobs = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "jobs": [job.to_dict() for job in self._jobs.values()],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def _trim(self) -> None:
        if len(self._jobs) <= 100:
            return
        ordered = sorted(self._jobs.values(), key=lambda item: item.created_at)
        for job in ordered:
            if len(self._jobs) <= 100:
                break
            if job.status in TERMINAL_STATUSES:
                self._jobs.pop(job.id, None)


def preview_svg(job: VideoJob) -> bytes:
    """Apercu anime deterministe pour le mode demo (jamais presente comme IA reelle)."""
    digest = hashlib.sha256(f"{job.id}:{job.request.prompt}".encode()).hexdigest()
    hues = [int(digest[index : index + 2], 16) * 360 // 255 for index in (0, 2, 4)]
    lines = _wrap(job.request.prompt, width=42, maximum=3)
    text = "".join(
        f'<text x="50%" y="{54 + index * 7}%" class="prompt">{html.escape(line)}</text>'
        for index, line in enumerate(lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="hsl({hues[0]} 75% 13%)"/>
    <stop offset="0.5" stop-color="hsl({hues[1]} 80% 22%)"/>
    <stop offset="1" stop-color="hsl({hues[2]} 72% 12%)"/>
    <animateTransform attributeName="gradientTransform" type="rotate" values="0 .5 .5;360 .5 .5" dur="12s" repeatCount="indefinite"/>
  </linearGradient>
  <filter id="blur"><feGaussianBlur stdDeviation="55"/></filter>
  <filter id="glow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <style>
    .brand {{ font:700 24px system-ui,sans-serif; letter-spacing:8px; fill:#fff; opacity:.9 }}
    .demo {{ font:600 15px system-ui,sans-serif; letter-spacing:3px; fill:#a5f3fc }}
    .prompt {{ font:600 34px system-ui,sans-serif; fill:white; text-anchor:middle }}
    .meta {{ font:400 18px system-ui,sans-serif; fill:#cbd5e1; text-anchor:middle }}
  </style>
</defs>
<rect width="1280" height="720" fill="#050713"/>
<rect width="1280" height="720" fill="url(#bg)" opacity=".85"/>
<circle cx="260" cy="230" r="210" fill="hsl({hues[0]} 90% 60% / .4)" filter="url(#blur)">
  <animate attributeName="cx" values="180;1040;180" dur="11s" repeatCount="indefinite"/>
</circle>
<circle cx="1030" cy="500" r="250" fill="hsl({hues[2]} 90% 60% / .35)" filter="url(#blur)">
  <animate attributeName="cy" values="560;150;560" dur="9s" repeatCount="indefinite"/>
</circle>
<g opacity=".16"><path d="M0 570 Q320 430 640 570 T1280 570 V720 H0Z" fill="#fff">
  <animate attributeName="d" dur="8s" repeatCount="indefinite" values="M0 570 Q320 430 640 570 T1280 570 V720 H0Z;M0 540 Q320 650 640 530 T1280 540 V720 H0Z;M0 570 Q320 430 640 570 T1280 570 V720 H0Z"/>
</path></g>
<text x="64" y="68" class="brand" filter="url(#glow)">NEXUS HLP.AI</text>
<text x="1100" y="65" class="demo">DEMO</text>
{text}
<text x="50%" y="80%" class="meta">{html.escape(job.request.style.upper())} · {job.request.aspect_ratio} · {job.request.duration}s · {job.request.resolution}</text>
<rect x="64" y="654" width="1152" height="3" rx="2" fill="#ffffff22"/>
<rect x="64" y="654" width="360" height="3" rx="2" fill="#67e8f9">
  <animate attributeName="x" values="64;856;64" dur="4s" repeatCount="indefinite"/>
</rect>
</svg>"""
    return svg.encode("utf-8")


def _wrap(text: str, *, width: int, maximum: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > width:
            lines.append(" ".join(current))
            current = [word]
            if len(lines) >= maximum:
                break
        else:
            current.append(word)
    if current and len(lines) < maximum:
        lines.append(" ".join(current))
    if len(lines) == maximum and len(" ".join(lines)) < len(text):
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return lines or ["Nexus HLP.AI"]
