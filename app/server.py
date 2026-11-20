#!/usr/bin/env python3
"""Application web locale du conseil ChatGPT x Claude x Gemini.

Un seul fichier serveur, **bibliotheque standard uniquement** : aucune
installation, aucun framework, aucun build. Il expose l'interface HTML de
``app/index.html`` et deux routes JSON qui executent le vrai moteur
``agents.council``.

    python app/server.py                 # http://localhost:8000
    python app/server.py --port 9000

Sans cle API, les trois sieges repondent en simulation deterministe ; les cartes
de l'interface indiquent clairement « simule » ou « reel ».
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ``python app/server.py`` place d'abord ``app/`` dans sys.path. Ajout explicite
# de la racine pour que le paquet ``agents`` soit importable sans installation.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.cli import council_label  # noqa: E402
from agents.core.budget import Budget  # noqa: E402
from agents.core.bus import EventBus, NullSink  # noqa: E402
from agents.core.errors import AgentError, ProviderError  # noqa: E402
from agents.core.llm import build_provider  # noqa: E402
from agents.council import Council, CouncilConfig, Member  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 32_000
MAX_QUESTION_CHARS = 2000
PERSONAS = (
    "rigueur chiffree : ordres de grandeur, priorites",
    "risques et cas limites : ce qui peut mal tourner",
    "clarte d'action : que faire concretement, dans quel ordre",
)
PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY", "gpt-4o-mini"),
    "anthropic": ("ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"),
    "gemini": ("GEMINI_API_KEY/GOOGLE_API_KEY", "gemini-2.0-flash"),
}


def provider_states() -> list[dict[str, Any]]:
    """Quels fournisseurs sont configures (sans jamais exposer les cles)."""
    return [
        {
            "name": name,
            "ready": bool(os.environ.get(env.split("/")[0]) or os.environ.get(env.split("/")[-1])),
            "model": (
                os.environ.get(f"AGENTS_{name.upper()}_MODEL")
                or os.environ.get("AGENTS_MODEL")
                or default_model
            ),
            "env": env,
        }
        for name, (env, default_model) in PROVIDER_ENV.items()
    ]


def default_app_specs() -> list[str]:
    """Trois specs explicites : provider reel configure, mock sinon."""
    return [
        f"{state['name']}:{state['model']}" if state["ready"] else f"mock:{state['name']}"
        for state in provider_states()
    ]


def _members_specs(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("models")
    if isinstance(raw, list) and raw:
        specs = [str(item).strip() for item in raw if str(item).strip()]
    else:
        specs = default_app_specs()
    if not specs:
        raise ValueError("aucun modele disponible")
    if len(specs) > 5:
        raise ValueError("5 membres maximum")
    return specs


def run_council(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute une deliberation et retourne le rapport serialisable.

    Leve ``ValueError`` pour une requete invalide, ``AgentError`` si la
    configuration du provider est en cause.
    """
    if not isinstance(payload, dict):
        raise ValueError("corps JSON attendu")
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question vide")
    question = " ".join(question.split())
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question trop longue (>{MAX_QUESTION_CHARS} caracteres)")

    try:
        rounds = int(payload.get("rounds", 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("rounds doit etre 1 ou 2") from exc
    if rounds not in {1, 2}:
        raise ValueError("rounds doit etre 1 ou 2")

    used: set[str] = set()
    members = [
        Member(
            label=council_label(spec, used),
            provider=build_provider(spec),
            persona=PERSONAS[index % len(PERSONAS)],
        )
        for index, spec in enumerate(_members_specs(payload))
    ]
    council = Council(
        members,
        config=CouncilConfig(
            rounds=rounds,
            concurrency=len(members),
            member_timeout_s=45.0,
            total_timeout_s=120.0,
            max_tokens=600,
        ),
        budget=Budget(max_llm_calls=30, max_tokens=60_000, max_seconds=150.0),
        bus=EventBus([NullSink()]),
    )
    report = asyncio.run(council.deliberate(question))
    data = report.to_dict()
    # On n'envoie au navigateur que ce qui est utile a l'affichage.
    data["contributions"] = [
        {
            "label": item["label"],
            "round": item["round"],
            "ok": item["ok"],
            "text": item["text"],
            "error": item["error"],
            "simulated": "mock" in str(item["label"]).lower(),
            "duration_ms": item["duration_ms"],
        }
        for item in data["contributions"]
    ]
    return data


class CouncilHandler(BaseHTTPRequestHandler):
    """Routes : ``/``, ``/api/health``, ``/api/providers``, ``/api/council``."""

    server_version = "multitask-agents/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"[app] {self.address_string()} {format % args}\n")

    # -------------------------------------------------------------- sorties
    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "fichier introuvable"})
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message})

    # --------------------------------------------------------------- routes
    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        if route in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif route == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "providers": provider_states(),
                    "default_models": default_app_specs(),
                },
            )
        elif route == "/api/providers":
            self._send_json(HTTPStatus.OK, {"providers": provider_states()})
        else:
            self._error(HTTPStatus.NOT_FOUND, "route inconnue")

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route != "/api/council":
            self._error(HTTPStatus.NOT_FOUND, "route inconnue")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "Content-Length invalide")
            return
        if length <= 0:
            self._error(HTTPStatus.BAD_REQUEST, "corps vide")
            return
        if length > MAX_BODY_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "corps trop volumineux")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "JSON invalide")
            return
        try:
            report = run_council(payload)
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except (AgentError, ProviderError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, getattr(exc, "message", str(exc)))
            return
        except Exception as exc:  # le serveur ne doit jamais mourir
            self.log_message("erreur interne: %s", exc)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")
            return
        self._send_json(HTTPStatus.OK, report)


def build_server(host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer:
    """Cree le serveur sans le demarrer (testable sur un port ephemere)."""
    server = ThreadingHTTPServer((host, port), CouncilHandler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Conseil ChatGPT x Claude x Gemini (app web locale)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="interface d'ecoute (defaut 0.0.0.0)")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="port d'ecoute (defaut : variable PORT ou 8000)",
    )
    args = parser.parse_args(argv)

    server = build_server(args.host, args.port)
    host, port = server.server_address[:2]
    ready = [item["name"] for item in provider_states() if item["ready"]]
    print(f"Conseil disponible sur http://localhost:{port}  (ecoute {host})")
    print(f"Providers configures : {', '.join(ready) or 'aucun — mode simulation'}")
    print("Ctrl+C pour arreter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\narret du serveur.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
