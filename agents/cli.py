"""Point d'entree en ligne de commande (``python -m agents`` / ``agents``).

Codes de sortie stables, utilisables en CI ou dans un script :

* ``0`` : run reussi ;
* ``1`` : run en echec (aucune tache reussie) ;
* ``2`` : erreur d'usage ou de configuration (provider, cle absente, arguments) ;
* ``3`` : run partiel (au moins une tache en echec ou rejetee) ;
* ``130`` : interruption clavier.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agents import __version__
from agents.agents.planner import heuristic_plan
from agents.core.budget import Budget
from agents.core.bus import ConsoleSink, EventBus, JsonlSink, NullSink
from agents.core.errors import AgentError
from agents.core.llm import build_provider
from agents.core.models import RunReport
from agents.core.registry import ToolRegistry
from agents.council import Council, CouncilConfig, CouncilReport, Member
from agents.orchestrator import Orchestrator, RunConfig
from agents.tools import build_registry, describe

DEFAULT_CORPUS = Path(__file__).resolve().parent / "data" / "corpus"
STATUS_LABEL = {
    "succeeded": "OK",
    "partial": "PARTIEL",
    "failed": "ECHEC",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents",
        description=(
            "Orchestrateur multi-agents (planification, taches paralleles outillees, "
            "critique, synthese) et conseil multi-modeles (ChatGPT x Claude x Gemini)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            '  agents run "Quel est le cout de 12 sieges a 249,99 USD ?"\n'
            '  agents run "Resume l\'architecture du projet" --provider mock --json run.json\n'
            '  agents plan "Auditer la securite des outils"\n'
            '  agents council "Faut-il un index ou une recherche plein texte ?"\n'
            '  agents council "question" --models openai:gpt-4o-mini,anthropic,gemini\n'
            "  agents tools\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="executer le pipeline complet sur un objectif")
    run.add_argument("objective", nargs="+", help="objectif en langage naturel")
    _common_options(run)
    run.add_argument("--json", metavar="PATH", help="ecrire le rapport JSON ('-' pour stdout)")
    run.add_argument("--trace", metavar="PATH", help="ecrire la trace JSONL des evenements")
    run.add_argument("--quiet", "-q", action="store_true", help="pas de progression sur stderr")
    run.add_argument("--verbose", "-v", action="store_true", help="details par tache")

    plan = sub.add_parser("plan", help="afficher le plan sans executer les taches")
    plan.add_argument("objective", nargs="+", help="objectif en langage naturel")
    _common_options(plan)
    plan.add_argument("--json", action="store_true", help="sortie JSON")
    plan.add_argument("--offline", action="store_true", help="plan heuristique, sans LLM")

    tools = sub.add_parser("tools", help="lister les outils disponibles")
    tools.add_argument("--json", action="store_true", help="sortie JSON")
    tools.add_argument("--workspace", default=".", help="racine du sandbox fichiers")
    tools.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="repertoire du corpus")

    council = sub.add_parser(
        "council", help="faire deliberer plusieurs modeles (ChatGPT x Claude x Gemini) puis juger"
    )
    council.add_argument("question", nargs="+", help="question soumise au conseil")
    council.add_argument(
        "--models",
        default="",
        help=(
            "sieges separes par des virgules, ex: openai:gpt-4o-mini,anthropic,gemini. "
            "Par defaut: les providers dont la cle est presente, completes par des mocks."
        ),
    )
    council.add_argument("--judge", default="", help="provider du juge (defaut: premier siege)")
    council.add_argument(
        "--rounds", type=int, default=2, help="1 = reponses + juge, 2 = + critique croisee"
    )
    council.add_argument(
        "--answer-tokens", type=int, default=700, help="longueur max par contribution"
    )
    council.add_argument(
        "--member-timeout", type=float, default=60.0, help="timeout par membre (s)"
    )
    council.add_argument("--total-timeout", type=float, default=240.0, help="timeout global (s)")
    council.add_argument("--max-tokens", type=int, default=120_000, help="budget de tokens")
    council.add_argument("--max-llm-calls", type=int, default=40, help="budget d'appels LLM")
    council.add_argument("--max-seconds", type=float, default=300.0, help="budget de duree (s)")
    council.add_argument("--json", metavar="PATH", help="ecrire le rapport JSON ('-' pour stdout)")
    council.add_argument("--trace", metavar="PATH", help="ecrire la trace JSONL")
    council.add_argument(
        "--quiet", "-q", action="store_true", help="n'afficher que la reponse finale"
    )
    council.add_argument(
        "--verbose", "-v", action="store_true", help="afficher chaque contribution"
    )

    providers = sub.add_parser("providers", help="lister les providers et leur etat")
    providers.add_argument("--json", action="store_true", help="sortie JSON")
    return parser


def _common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        default="mock",
        help="mock (hors ligne, defaut) | openai[:modele] | anthropic[:modele]",
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="repertoire du corpus")
    parser.add_argument("--workspace", default=".", help="racine du sandbox fichiers")
    parser.add_argument("--concurrency", type=int, default=3, help="taches en parallele")
    parser.add_argument("--max-steps", type=int, default=None, help="etapes ReAct par tache")
    parser.add_argument("--task-timeout", type=float, default=45.0, help="timeout par tache (s)")
    parser.add_argument("--run-timeout", type=float, default=300.0, help="timeout global (s)")
    parser.add_argument("--max-attempts", type=int, default=2, help="tentatives par tache")
    parser.add_argument("--max-tokens", type=int, default=120_000, help="budget de tokens")
    parser.add_argument("--max-llm-calls", type=int, default=40, help="budget d'appels LLM")
    parser.add_argument("--max-seconds", type=float, default=300.0, help="budget de duree (s)")
    parser.add_argument(
        "--revise-below",
        type=float,
        default=0.7,
        help="seuil de score sous lequel une tache est revisee",
    )
    parser.add_argument("--no-revise", action="store_true", help="desactiver la boucle de revision")
    parser.add_argument("--allow-write", action="store_true", help="activer file_write")


def main(argv: list[str] | None = None) -> int:
    """Execute la commande demandee et retourne un code de sortie."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "plan":
            return _cmd_plan(args)
        if args.command == "tools":
            return _cmd_tools(args)
        if args.command == "council":
            return _cmd_council(args)
        if args.command == "providers":
            return _cmd_providers(args)
    except AgentError as exc:
        print(f"erreur : {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"indice : {exc.hint}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrompu par l'utilisateur", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"argument invalide : {exc}", file=sys.stderr)
        return 2
    return 2  # pragma: no cover - argparse couvre ce cas


# ------------------------------------------------------------------ commandes
def _cmd_run(args: argparse.Namespace) -> int:
    objective = " ".join(args.objective).strip()
    provider = build_provider(args.provider)
    registry = _registry(args)
    bus = EventBus([NullSink()])
    if not args.quiet:
        bus.add_sink(ConsoleSink())
    if args.trace:
        bus.add_sink(JsonlSink(args.trace))

    orchestrator = Orchestrator(
        provider=provider,
        registry=registry,
        config=RunConfig(
            concurrency=args.concurrency,
            task_timeout_s=args.task_timeout,
            run_timeout_s=args.run_timeout,
            max_attempts=args.max_attempts,
            revise_below=args.revise_below,
            max_revisions=0 if args.no_revise else 1,
            max_steps=args.max_steps,
        ),
        budget=Budget(
            max_llm_calls=args.max_llm_calls,
            max_tokens=args.max_tokens,
            max_seconds=args.max_seconds,
        ),
        bus=bus,
    )
    report = asyncio.run(orchestrator.run(objective))
    if args.json != "-":
        _print_report(report, verbose=args.verbose, quiet=args.quiet)

    if args.json:
        payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json == "-":
            print(payload)
        else:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload + "\n", encoding="utf-8")
            if not args.quiet:
                print(f"\nrapport JSON ecrit dans {path}", file=sys.stderr)

    return {"succeeded": 0, "partial": 3, "failed": 1}[report.status]


def _cmd_plan(args: argparse.Namespace) -> int:
    objective = " ".join(args.objective).strip()
    registry = _registry(args)
    if args.offline:
        plan = heuristic_plan(objective, available_tools=registry.names())
    else:
        provider = build_provider(args.provider)
        orchestrator = Orchestrator(provider=provider, registry=registry)
        plan = asyncio.run(orchestrator.planner.plan(objective, available_tools=registry.names()))
    payload = plan.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"objectif : {plan.objective}")
    print(f"source   : {plan.source}\n")
    for batch_index, batch in enumerate(plan.topological_batches(), start=1):
        ids = ", ".join(task.id for task in batch)
        print(f"vague {batch_index} (parallele) : {ids}")
        for task in batch:
            deps = f" <- {', '.join(task.depends_on)}" if task.depends_on else ""
            print(f"  - {task.id} {task.title}{deps}")
            print(f"    {task.instruction[:160]}")
    return 0


def _cmd_tools(args: argparse.Namespace) -> int:
    registry = build_registry(workspace=args.workspace, corpus_dir=args.corpus, allow_write=False)
    items = describe(registry)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    print(f"{len(items)} outil(s) disponible(s) :\n")
    for item in items:
        required = ", ".join(item["required"]) or "aucun"
        print(f"- {item['name']} (timeout {item['timeout_s']:.0f}s, requis : {required})")
        print(f"    {item['description']}")
    return 0


def _cmd_providers(args: argparse.Namespace) -> int:
    import os

    items = [
        {"name": "mock", "requires_key": False, "ready": True, "note": "hors ligne, deterministe"},
        {
            "name": "openai",
            "requires_key": True,
            "ready": bool(os.environ.get("OPENAI_API_KEY")),
            "note": "OPENAI_API_KEY",
        },
        {
            "name": "anthropic",
            "requires_key": True,
            "ready": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "note": "ANTHROPIC_API_KEY",
        },
        {
            "name": "gemini",
            "requires_key": True,
            "ready": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
            "note": "GEMINI_API_KEY / GOOGLE_API_KEY",
        },
    ]
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    for item in items:
        state = "pret" if item["ready"] else "cle absente"
        extra = "" if item["requires_key"] else " (aucune configuration)"
        print(f"- {item['name']:<10} {state:<12}{extra}  [{item['note']}]")
    print(
        "\nAstuce : 'agents council \"question\"' selectionne automatiquement les providers "
        "dont la cle est presente."
    )
    return 0


_COUNCIL_BRANDS = {"openai": "ChatGPT", "anthropic": "Claude", "gemini": "Gemini"}
_COUNCIL_PERSONAS = (
    "rigueur chiffree : ordres de grandeur, ordres de priorite",
    "risques et cas limites : ce qui peut mal tourner",
    "clarte d'action : que faire concretement, dans quel ordre",
)


def default_council_specs(env: dict[str, str] | None = None) -> list[str]:
    """Trois sieges : les providers configures, completes par des mocks hors ligne."""
    import os

    environ = os.environ if env is None else env
    keys = {
        "openai": environ.get("OPENAI_API_KEY"),
        "anthropic": environ.get("ANTHROPIC_API_KEY"),
        "gemini": environ.get("GEMINI_API_KEY") or environ.get("GOOGLE_API_KEY"),
    }
    specs = [name for name, key in keys.items() if key]
    for name in ("openai", "anthropic", "gemini"):
        if len(specs) >= 3:
            break
        if name not in specs:
            specs.append(f"mock:{name}")
    return specs


def council_label(spec: str, used: set[str]) -> str:
    """Etiquette lisible et unique pour un siege."""
    name = spec.split(":", 1)[0].strip().lower()
    model = spec.partition(":")[2].strip()
    if name in {"mock", "offline"}:
        # un siege mock represente une marque reelle : "mock:openai" -> ChatGPT (mock)
        brand = _COUNCIL_BRANDS.get(model.lower(), model or "membre")
        label = f"{brand} (mock)"
    else:
        label = _COUNCIL_BRANDS.get(name, model or name or "membre")
    if label in used:
        index = 2
        while f"{label} #{index}" in used:
            index += 1
        label = f"{label} #{index}"
    used.add(label)
    return label


def _cmd_council(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip()
    specs = [spec.strip() for spec in args.models.split(",") if spec.strip()]
    if not specs:
        specs = default_council_specs()

    used: set[str] = set()
    members = [
        Member(
            label=council_label(spec, used),
            provider=build_provider(spec),
            persona=_COUNCIL_PERSONAS[index % len(_COUNCIL_PERSONAS)],
        )
        for index, spec in enumerate(specs)
    ]
    judge = Member(label="Juge", provider=build_provider(args.judge)) if args.judge else None
    bus = EventBus([NullSink()])
    if not args.quiet:
        bus.add_sink(ConsoleSink())
    if args.trace:
        bus.add_sink(JsonlSink(args.trace))

    council = Council(
        members,
        judge=judge,
        config=CouncilConfig(
            rounds=args.rounds,
            concurrency=max(1, len(members)),
            member_timeout_s=args.member_timeout,
            total_timeout_s=args.total_timeout,
            max_tokens=args.answer_tokens,
        ),
        budget=Budget(
            max_llm_calls=args.max_llm_calls,
            max_tokens=args.max_tokens,
            max_seconds=args.max_seconds,
        ),
        bus=bus,
    )
    report = asyncio.run(council.deliberate(question))

    if args.json != "-":
        _print_council_report(report, verbose=args.verbose, quiet=args.quiet)
    if args.json:
        payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json == "-":
            print(payload)
        else:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload + "\n", encoding="utf-8")
            if not args.quiet:
                print(f"\nrapport JSON ecrit dans {path}", file=sys.stderr)
    return {"succeeded": 0, "partial": 3, "failed": 1}[report.status]


def _print_council_report(report: CouncilReport, *, verbose: bool, quiet: bool) -> None:
    if quiet:
        print(report.answer)
        return
    width = 62
    print()
    print("=" * width)
    status = STATUS_LABEL.get(report.status, report.status.upper())
    print(f"conseil {status} — {' / '.join(report.members)}")
    print("=" * width)
    print(f"question : {' '.join(report.question.split())[:200]}")
    print(f"juge     : {report.judge}")
    print(f"duree    : {report.duration_ms / 1000:.2f}s")
    print(f"tokens   : {report.usage.total_tokens} ({report.usage.llm_calls} appel(s) LLM)")
    print()
    for contribution in report.contributions:
        state = "ok " if contribution.ok else "err"
        print(
            f"  [{state}] {contribution.label:<18} tour {contribution.round} "
            f"{contribution.duration_ms:7.0f}ms  {len(contribution.text):4d} car."
        )
        if verbose and contribution.ok:
            print(f"        {' '.join(contribution.text.split())[:240]}")
        if not contribution.ok:
            print(f"        erreur : {contribution.error}")
    for error in report.errors:
        print(f"  ! {error}")
    print()
    print("-" * width)
    print("REPONSE FINALE")
    print("-" * width)
    print(report.answer)


# ------------------------------------------------------------------- sorties
def _registry(args: argparse.Namespace) -> ToolRegistry:
    return build_registry(
        workspace=args.workspace,
        corpus_dir=args.corpus,
        allow_write=getattr(args, "allow_write", False),
    )


def _print_report(report: RunReport, *, verbose: bool, quiet: bool) -> None:
    if quiet:
        print(report.final_answer)
        return
    width = 62
    print()
    print("=" * width)
    print(f"run {report.run_id} — {STATUS_LABEL.get(report.status, report.status)}")
    print("=" * width)
    print(f"provider      : {report.provider}")
    print(f"plan ({report.plan.source:<8}) : {len(report.plan.tasks)} tache(s)")
    print(f"duree         : {report.duration_ms / 1000:.2f}s")
    print(f"tokens        : {report.usage.total_tokens} ({report.usage.llm_calls} appel(s) LLM)")
    print()
    for result in report.results:
        score = f"{result.review.score:.2f}" if result.review else "  - "
        verdict = result.review.verdict if result.review else "-"
        line = (
            f"  [{result.status:<9}] {result.task_id:<4} score {score} {verdict:<6} "
            f"{result.duration_ms:7.0f}ms  essais={result.attempts}"
        )
        print(line)
        if verbose:
            if result.error:
                print(f"      erreur : {result.error}")
            if result.output:
                snippet = " ".join(result.output.split())[:220]
                print(f"      sortie : {snippet}")
            if result.review and result.review.issues:
                print(f"      avis   : {'; '.join(result.review.issues)}")
    for error in report.errors:
        print(f"  ! {error}")
    print()
    print("-" * width)
    print("REPONSE FINALE")
    print("-" * width)
    print(report.final_answer)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
