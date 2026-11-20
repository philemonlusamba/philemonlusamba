#!/usr/bin/env python3
"""Serveur web sans framework de Nexus HLP.AI.

    python -m nexus.server
    python -m nexus.server --port 8001

Le navigateur ne recoit jamais les secrets. Toutes les cles restent dans les
variables d'environnement du serveur.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from nexus import __version__
from nexus.catalog import connector_states, public_catalog
from nexus.jobs import JobNotFound, JobStore, preview_svg
from nexus.models import ValidationError, VideoRequest
from nexus.providers import GenerationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 256_000
JOB_ROUTE_RE = re.compile(r"^/api/jobs/([a-f0-9]{12})(?:/(cancel|preview\.svg))?$")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class NexusHTTPServer(ThreadingHTTPServer):
    """HTTP server portant son propre store pour rendre les tests isoles."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: JobStore) -> None:
        super().__init__(address, NexusHandler)
        self.store = store


class NexusHandler(BaseHTTPRequestHandler):
    """API JSON et fichiers statiques de l'application."""

    server_version = f"NexusHLP/{__version__}"

    @property
    def store(self) -> JobStore:
        return self.server.store  # type: ignore[attr-defined,no-any-return]

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"[nexus] {self.address_string()} {format % args}\n")

    # --------------------------------------------------------------- reponses
    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; media-src 'self' blob: https: http:; "
            "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'",
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        cache: str = "no-store",
        disposition: str = "",
    ) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        if self.command != "HEAD":
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send_bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _error(self, status: HTTPStatus, message: str, *, hint: str = "") -> None:
        payload = {"error": message}
        if hint:
            payload["hint"] = hint
        self._json(status, payload)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValidationError("Content-Length invalide") from exc
        if length <= 0:
            raise ValidationError("corps JSON vide")
        if length > MAX_BODY_BYTES:
            raise ValidationError("corps JSON trop volumineux")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("JSON invalide") from exc
        if not isinstance(value, dict):
            raise ValidationError("un objet JSON est attendu")
        return value

    # ----------------------------------------------------------------- routes
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        route = parsed.path
        if route in STATIC_FILES:
            filename, content_type = STATIC_FILES[route]
            path = STATIC_DIR / filename
            if not path.is_file():
                self._error(HTTPStatus.NOT_FOUND, "fichier statique introuvable")
                return
            cache = "public, max-age=3600" if route.startswith("/static/") else "no-cache"
            self._send_bytes(HTTPStatus.OK, path.read_bytes(), content_type, cache=cache)
            return
        if route == "/api/health":
            connectors = connector_states(self.store.env)
            configured = [item.id for item in connectors if item.configured]
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "name": "Nexus HLP.AI",
                    "version": __version__,
                    "configured_connectors": configured,
                    "mode": "hybride" if len(configured) > 1 else "demo",
                    "stats": self.store.stats(),
                },
            )
            return
        if route == "/api/catalog":
            self._json(HTTPStatus.OK, public_catalog(self.store.env))
            return
        if route == "/api/jobs":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["50"])[0])
            except ValueError:
                limit = 50
            self._json(
                HTTPStatus.OK,
                {
                    "jobs": [job.to_dict() for job in self.store.list(limit=limit)],
                    "stats": self.store.stats(),
                },
            )
            return
        match = JOB_ROUTE_RE.fullmatch(route)
        if match:
            job_id, action = match.groups()
            try:
                job = self.store.get(job_id)
            except JobNotFound:
                self._error(HTTPStatus.NOT_FOUND, "generation introuvable")
                return
            if action == "preview.svg":
                self._send_bytes(
                    HTTPStatus.OK,
                    preview_svg(job),
                    "image/svg+xml; charset=utf-8",
                    cache="no-cache",
                    disposition=f'inline; filename="nexus-{job.id}.svg"',
                )
            elif action:
                self._error(HTTPStatus.METHOD_NOT_ALLOWED, "methode non acceptee")
            else:
                self._json(HTTPStatus.OK, {"job": job.to_dict()})
            return
        self._error(HTTPStatus.NOT_FOUND, "route inconnue")

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if route == "/api/jobs":
            try:
                request = VideoRequest.from_payload(self._read_json())
                job = self.store.submit(request)
            except ValidationError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except GenerationError as exc:
                self._error(
                    HTTPStatus.CONFLICT,
                    str(exc),
                    hint="configurez le connecteur cote serveur ou choisissez Nexus Demo",
                )
                return
            self._json(HTTPStatus.ACCEPTED, {"job": job.to_dict()})
            return

        match = JOB_ROUTE_RE.fullmatch(route)
        if match and match.group(2) == "cancel":
            try:
                job = self.store.cancel(match.group(1))
            except JobNotFound:
                self._error(HTTPStatus.NOT_FOUND, "generation introuvable")
                return
            self._json(HTTPStatus.OK, {"job": job.to_dict()})
            return
        self._error(HTTPStatus.NOT_FOUND, "route inconnue")

    def do_DELETE(self) -> None:
        route = urlsplit(self.path).path
        match = JOB_ROUTE_RE.fullmatch(route)
        if not match or match.group(2):
            self._error(HTTPStatus.NOT_FOUND, "route inconnue")
            return
        try:
            self.store.delete(match.group(1))
        except JobNotFound:
            self._error(HTTPStatus.NOT_FOUND, "generation introuvable")
            return
        except GenerationError as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
            return
        self._json(HTTPStatus.OK, {"deleted": match.group(1)})


def build_server(
    host: str = "0.0.0.0",
    port: int = 8001,
    *,
    store: JobStore | None = None,
) -> NexusHTTPServer:
    """Construit le serveur, testable avec ``port=0``."""
    job_store = store or JobStore(PROJECT_ROOT / "runs" / "nexus_jobs.json")
    return NexusHTTPServer((host, port), job_store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexus HLP.AI — generateur video multi-modeles")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8001")))
    args = parser.parse_args(argv)

    server = build_server(args.host, args.port)
    host, port = server.server_address[:2]
    configured = [item.name for item in connector_states(server.store.env) if item.configured]
    print(f"Nexus HLP.AI disponible sur http://localhost:{port}  (ecoute {host})")
    print(f"Connecteurs actifs : {', '.join(configured)}")
    print("Ctrl+C pour arreter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\narret de Nexus.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
