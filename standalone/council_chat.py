#!/usr/bin/env python3
"""Conseil ChatGPT x Claude x Gemini — fichier unique, zero dependance.

Copiez ce fichier dans VS Code, enregistrez-le sous ``council_chat.py``,
puis lancez :

    python council_chat.py "Faut-il un index SQL ou une recherche plein texte ?"
    python council_chat.py                      # mode interactif
    python council_chat.py "question" --rounds 2

Aucune installation, aucun ``pip install`` : uniquement la bibliotheque standard.

* Sans cle API, les trois sieges sont **simules** (reponses deterministes) pour
  que le programme tourne et s'affiche correctement des la premiere seconde.
* Des qu'une cle est presente dans l'environnement, le vrai modele prend le
  relais pour ce siege :

      export OPENAI_API_KEY=sk-...
      export ANTHROPIC_API_KEY=sk-ant-...
      export GEMINI_API_KEY=AIza...        (ou GOOGLE_API_KEY)

Deroulement : chaque siege repond, puis lit les reponses des autres
**anonymisees (A, B, C)**, se corrige si necessaire, et un juge produit une
synthese Consensus / Divergences / Reponse finale / Confiance.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TIMEOUT_S = 90
MAX_TOKENS = 700
ANONYM = "ABCDEFGH"

SYSTEM_MEMBER = """Tu es membre d'un conseil de plusieurs IA.
Tu reponds seul a la question. Sois precis et concis : 6 lignes maximum, en francais.
Commence par la reponse directe, puis 2 a 3 points d'appui.
Si un chiffre ou un fait n'est pas verifiable, dis-le. N'invente aucune source."""

SYSTEM_CRITIQUE = """Deuxieme tour d'un conseil de plusieurs IA.
Tu recois ta reponse et celles des autres membres, anonymisees (A, B, C).
Signale les erreurs que tu repere chez les autres, corrige ta propre reponse si
l'un a raison, sinon justifie ton maintien en une phrase.
Termine par "Reponse revisee:" suivie de ta version finale, en 4 lignes max."""

SYSTEM_JUDGE = """Tu es le juge d'un conseil de plusieurs IA.
A partir de la question et des reponses finales de chaque membre, produis :

## Consensus
2 a 4 puces sur les points d'accord.

## Divergences
Les desaccords, en nommant les membres. Sinon "Aucune divergence majeure".

## Reponse finale
La reponse a la question, sans ajouter aucun fait absent des contributions.

## Confiance
eleve, moyen ou faible, avec une justification en une phrase."""


@dataclass
class Seat:
    """Un siege du conseil : une marque, un fournisseur, un angle."""

    name: str
    provider: str
    model: str
    angle: str
    enabled: bool = True


@dataclass
class Contribution:
    """Une prise de parole (tour 1 = proposition, tour 2 = revision)."""

    seat: str
    round: int
    text: str = ""
    error: str = ""
    simulated: bool = False
    seconds: float = 0.0
    history: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


# --------------------------------------------------------------- fournisseurs
def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def call_openai(seat: Seat, system: str, user: str, key: str) -> str:
    payload = {
        "model": seat.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
    }
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    data = _post_json(
        f"{base_url}/chat/completions",
        payload,
        {"Authorization": f"Bearer {key}"},
    )
    return (data["choices"][0]["message"].get("content") or "").strip()


def call_anthropic(seat: Seat, system: str, user: str, key: str) -> str:
    payload = {
        "model": seat.model,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
    data = _post_json(
        f"{base_url}/messages",
        payload,
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return "\n".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    ).strip()


def call_gemini(seat: Seat, system: str, user: str, key: str) -> str:
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_TOKENS},
    }
    base_url = os.environ.get(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    data = _post_json(
        f"{base_url}/models/{seat.model}:generateContent",
        payload,
        {"x-goog-api-key": key},
    )
    parts = data["candidates"][0]["content"]["parts"]
    return "\n".join(part.get("text", "") for part in parts).strip()


def call_mock(seat: Seat, system: str, user: str) -> str:
    """Reponse simulee, deterministe et lisible (aucune cle requise)."""
    question = _section(user, "QUESTION") or user
    question = " ".join(question.split())[:200]
    keywords = _keywords(question)[:90] or "les elements disponibles"

    if "REPONSES ANONYMES" in user:
        return (
            f"[{seat.name}] Revision apres lecture croisee.\n"
            "- Les reponses anonymes ne contredisent pas mon analyse sur le fond.\n"
            f"- Point renforce : {keywords}.\n"
            "- Reservation maintenue : toute donnee chiffree doit etre verifiee.\n"
            "Reponse revisee: conclusion confirmee, avec la reserve ci-dessus."
        )
    return (
        f"[{seat.name}] Reponse directe : traiter la demande en isolant les faits "
        f"verifiables ({keywords}).\n"
        f"- Analyse : {seat.angle}\n"
        "- Verification : tout chiffre doit venir d'un outil ou d'une source citee.\n"
        "- Incertitude : le perimetre exact de la question reste a preciser."
    )


def call_mock_judge(question: str, contributions: list[Contribution]) -> str:
    """Synthese simulee du juge."""
    labels = ", ".join(item.seat for item in contributions if item.ok) or "aucun membre"
    bullets = []
    for item in contributions:
        if item.ok:
            first = " ".join(item.text.split())[:180]
            bullets.append(f"- **{item.seat}** : {first}")
    return (
        "## Consensus\n"
        f"- Les membres suivants ont repondu : {labels}.\n"
        "- Accord methodologique : repondre d'abord, verifier ensuite.\n\n"
        "## Divergences\n"
        "- Aucune divergence majeure : sorties generees hors ligne (mode simulation).\n\n"
        "## Reponse finale\n"
        f"Question : {question[:200]}\n\n" + "\n".join(bullets) + "\n\n"
        "## Confiance\n"
        "moyen — simulation locale ; renseignez une cle API pour un vrai passage de modeles."
    )


def _section(text: str, name: str) -> str:
    match = re.search(rf"\[\[{name}\]\]\s*(.*?)(?=\[\[[A-Z_ ]+\]\]|\Z)", text, re.S)
    return match.group(1).strip() if match else ""


def _keywords(text: str) -> str:
    stop = {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "de",
        "du",
        "dans",
        "sur",
        "pour",
        "avec",
        "et",
        "ou",
        "en",
        "au",
        "aux",
        "ce",
        "cette",
        "est",
        "sont",
        "que",
        "qui",
        "il",
        "elle",
        "on",
        "nous",
        "vous",
        "faut",
        "quel",
        "quelle",
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "and",
        "or",
        "for",
        "with",
        "is",
        "are",
    }
    words = re.findall(r"[\w'À-ÿ]+", text.lower())
    kept = [word for word in words if len(word) > 2 and word not in stop]
    return " ".join(dict.fromkeys(kept))


# ------------------------------------------------------------------- conseil
def ask(seat: Seat, system: str, user: str) -> Contribution:
    """Interroge un siege et capture toute erreur sans interrompre le conseil.

    Sans cle API, le siege bascule en simulation deterministe : le programme
    reste executable et lisible, et chaque reponse le signale explicitement.
    """
    key = _key_for(seat.provider)
    if seat.provider == "mock" or not key:
        text = call_mock(seat, system, user)
        if not text:
            return Contribution(seat=seat.name, round=1, error="reponse simulee vide")
        return Contribution(seat=seat.name, round=1, text=text, simulated=True)
    try:
        if seat.provider == "openai":
            text = call_openai(seat, system, user, key)
        elif seat.provider == "anthropic":
            text = call_anthropic(seat, system, user, key)
        elif seat.provider == "gemini":
            text = call_gemini(seat, system, user, key)
        else:
            text = call_mock(seat, system, user)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        return Contribution(seat=seat.name, round=1, error=f"HTTP {exc.code}: {detail}")
    except Exception as exc:
        return Contribution(seat=seat.name, round=1, error=f"{type(exc).__name__}: {exc}")
    if not text:
        return Contribution(seat=seat.name, round=1, error="reponse vide")
    return Contribution(seat=seat.name, round=1, text=text)


def _key_for(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY", "")
    if provider == "gemini":
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return ""


def build_seats() -> list[Seat]:
    """Trois sieges : le vrai fournisseur si sa cle existe, sinon simulation."""
    catalogue = [
        (
            "ChatGPT",
            "openai",
            os.environ.get("AGENTS_OPENAI_MODEL", "gpt-4o-mini"),
            "rigueur chiffree : ordres de grandeur et priorites",
        ),
        (
            "Claude",
            "anthropic",
            os.environ.get("AGENTS_ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            "risques et cas limites : ce qui peut mal tourner",
        ),
        (
            "Gemini",
            "gemini",
            os.environ.get("AGENTS_GEMINI_MODEL", "gemini-2.0-flash"),
            "clarte d'action : quoi faire, dans quel ordre",
        ),
    ]
    seats = []
    for name, provider, model, angle in catalogue:
        seats.append(
            Seat(
                name=name,
                provider=provider,
                model=model,
                angle=angle,
                enabled=bool(_key_for(provider)),
            )
        )
    return seats


def anonymised(own: str, contributions: list[Contribution]) -> str:
    """Reponses des autres, etiquetees A, B, C... et nom d'auteur retire."""
    healthy = [item for item in contributions if item.ok and item.seat != own]
    blocks = []
    for position, item in enumerate(healthy):
        alias = ANONYM[position % len(ANONYM)]
        text = item.text.replace(item.seat, alias)
        blocks.append(f"### {alias}\n{text}")
    return "\n\n".join(blocks) or "Aucune autre reponse exploitable."


def deliberate(question: str, *, rounds: int = 2) -> tuple[list[Contribution], str]:
    """Execute la deliberation et retourne (contributions, reponse finale)."""
    seats = build_seats()
    contributions: list[Contribution] = []

    print("\nTour 1 — propositions independantes")
    for seat in seats:
        print(f"  ... {seat.name}", end="", flush=True)
        contribution = ask(seat, SYSTEM_MEMBER, f"[[QUESTION]]\n{question}")
        contribution.history.append(contribution.text)
        contributions.append(contribution)
        if contribution.ok:
            tag = "simule" if contribution.simulated else "ok"
        else:
            tag = f"erreur: {contribution.error}"
        print(f"\r  [{tag}] {seat.name} — {len(contribution.text)} caracteres")

    if rounds >= 2:
        print("\nTour 2 — critique croisee (reponses anonymisees)")
        for index, seat in enumerate(seats):
            own = next((item for item in contributions if item.seat == seat.name), None)
            if own is None or not own.ok:
                continue
            prompt = (
                f"[[QUESTION]]\n{question}\n\n"
                f"[[VOTRE REPONSE]]\n{own.text}\n\n"
                f"[[REPONSES ANONYMES]]\n{anonymised(seat.name, contributions)}"
            )
            revised = ask(seat, f"{SYSTEM_MEMBER}\n\n{SYSTEM_CRITIQUE}", prompt)
            if revised.ok:
                revised.round = 2
                revised.history = [*own.history, revised.text]
                contributions[index] = revised
                tag = "simule" if revised.simulated else "ok"
                print(f"  [{tag}] {seat.name} — revision de {len(revised.text)} caracteres")
            else:
                print(f"  [conserve] {seat.name} — {revised.error}")

    finals = [item for item in contributions if item.ok]
    if not finals:
        erreurs = "; ".join(item.error for item in contributions) or "inconnue"
        return contributions, f"Aucun membre n'a repondu. Erreurs : {erreurs}"

    print("\nJuge — synthese")
    judge_seat = next((seat for seat in seats if seat.enabled), None)
    if judge_seat is None:
        return contributions, call_mock_judge(question, finals)
    blocks = "\n\n".join(f"### {item.seat}\n{item.text}" for item in finals)
    prompt = f"[[QUESTION]]\n{question}\n\n[[CONTRIBUTIONS]]\n{blocks}"
    verdict = ask(judge_seat, SYSTEM_JUDGE, prompt)
    return contributions, verdict.text or call_mock_judge(question, finals)


# ------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    rounds = 2
    as_json = False
    if "--rounds" in args:
        position = args.index("--rounds")
        try:
            rounds = int(args[position + 1])
        except (IndexError, ValueError):
            print("--rounds attend 1 ou 2", file=sys.stderr)
            return 2
        del args[position : position + 2]
    if rounds not in {1, 2}:
        print("--rounds attend 1 ou 2", file=sys.stderr)
        return 2
    if "--no-critique" in args:
        rounds = 1
        args.remove("--no-critique")
    if "--json" in args:
        as_json = True
        args.remove("--json")
    if args and args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0

    seats = build_seats()
    configured = sum(seat.enabled for seat in seats)
    mode = "reel" if configured == len(seats) else "hybride" if configured else "simulation"
    print(f"Conseil : {' / '.join(seat.name for seat in seats)}  (mode {mode}, {rounds} tour(s))")

    question = " ".join(args).strip()
    if not question:
        try:
            question = input("\nVotre question : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nannule.")
            return 130
    if not question:
        print("question vide.", file=sys.stderr)
        return 2

    contributions, answer = deliberate(question, rounds=rounds)
    if as_json:
        print(
            json.dumps(
                {
                    "question": question,
                    "answer": answer,
                    "contributions": [
                        {
                            "seat": item.seat,
                            "round": item.round,
                            "ok": item.ok,
                            "error": item.error,
                            "text": item.text,
                        }
                        for item in contributions
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if answer.startswith("##") or "Reponse" in answer else 1

    print("\n" + "=" * 64)
    print(answer)
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
