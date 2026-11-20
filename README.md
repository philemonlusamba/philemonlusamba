# multitask-agents

Orchestrateur **multi-agents en Python** : un objectif en langage naturel est
découpé en un graphe de tâches, exécutées **en parallèle** par des workers
outillés, puis **critiquées**, corrigées si nécessaire et synthétisées.

Le tout tourne **hors ligne, sans clé API et sans coût** grâce à un provider
`mock` déterministe. Brancher OpenAI ou Anthropic se fait par une variable
d'environnement.

```bash
pip install -e ".[dev]"
python -m agents run "Combien coûtent 12 x 249,99 USD, et que dit la doc sur la sécurité des outils ?"
```

```
==============================================================
run 0f954244089c — OK
==============================================================
provider      : mock
plan (llm     ) : 3 tache(s)
duree         : 0.01s
tokens        : 3501 (10 appel(s) LLM)

  [succeeded] t1   score 0.86 accept       4ms  essais=1
  [succeeded] t2   score 0.86 accept       3ms  essais=1
  [succeeded] t3   score 0.86 accept       0ms  essais=1

--------------------------------------------------------------
REPONSE FINALE
--------------------------------------------------------------
## Reponse

Objectif traite : Combien coutent 12 x 249,99 USD, et que dit la doc sur la securite ?

**t1 — Calcul** (confiance 0.86)

Resultat obtenu via outil(s): 2999.88 (expression: 12*249.99, ...)
**t2 — Recherche documentaire** (confiance 0.86)
...[securite.md] Les outils sont la surface d'attaque principale...
**t3 — Redaction** (confiance 0.86)
Synthese des elements amont : [t1] ... [t2] ...
```

## Conseil multi-modèles (ChatGPT × Claude × Gemini)

```bash
# hors ligne : trois sièges simulés, délibération complète
python -m agents council "Faut-il un index SQL ou une recherche plein texte pour 50 000 documents ?"

# production : dès qu'une clé est présente, le siège réel est utilisé
export OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... GEMINI_API_KEY=AIza...
python -m agents council "Même question, avec les vrais modèles"
```

```
conseil OK — ChatGPT (mock) / Claude (mock) / Gemini (mock)
question : Faut-il un index SQL ou une recherche plein texte pour 50 000 documents ?
juge     : ChatGPT (mock)
tokens   : 3465 (7 appel(s) LLM)

  [ok ] ChatGPT (mock)     tour 1       0ms   396 car.
  [ok ] Claude (mock)      tour 1       0ms   370 car.
  [ok ] Gemini (mock)      tour 1       0ms   387 car.
  [ok ] ChatGPT (mock)     tour 2       1ms   405 car.
  ...
```

Déroulé de la délibération (`agents/council.py`) :

1. **tour 1 — propositions** : chaque membre répond seul, en parallèle, avec un
   angle imposé (rigueur chiffrée / risques / clarté d'action) pour éviter trois
   réponses interchangeables ;
2. **tour 2 — critique croisée** : chacun reçoit les réponses des autres
   **anonymisées en A, B, C**, et doit soit corriger sa réponse, soit justifier
   son maintien. Le nom de l'auteur est aussi retiré *du texte* de la réponse :
   sans ça, une réponse signée « Claude » réintroduit le biais de marque que
   l'anonymisation cherche à supprimer ;
3. **juge** : une synthèse structurée en `Consensus` / `Divergences` /
   `Réponse finale` / `Confiance`, qui n'ajoute aucun fait absent des
   contributions et signale les membres défaillants.

Robustesse : un membre qui échoue ou dépasse son timeout rend le rapport
`partiel` sans annuler le conseil ; si le juge échoue, la réponse de repli
reprend les contributions brutes ; si tous les membres échouent, le statut est
`échec` avec les erreurs listées.

`--models` accepte n'importe quelle combinaison :
`--models openai:gpt-4o-mini,anthropic:claude-3-5-sonnet-latest,gemini:gemini-2.0-flash`,
et `--judge` désigne un siège distinct pour arbitrer.

## Le pipeline

```
                 ┌──────────┐
  objectif  ───► │ PLANNER  │ ───► DAG de tâches
                 └──────────┘
                       │
        ┌──────────────┼──────────────┐        (exécution concurrente,
        ▼              ▼              ▼         limitée par sémaphore)
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ WORKER  │   │ WORKER  │   │ WORKER  │ ◄── outils sandboxés
   │  (t1)   │   │  (t2)   │   │  (t3)   │     (calcul, recherche,
   └────┬────┘   └────┬────┘   └────┬────┘      fichiers, texte)
        └──────────────┼──────────────┘
                       ▼
                 ┌──────────┐   score 0..1 + corrections
                 │  CRITIC  │ ───► révision d'une tâche si insuffisante
                 └──────────┘
                       ▼
                 ┌──────────────┐
                 │ SYNTHESIZER  │ ───► réponse finale citant (t1), (t2)...
                 └──────────────┘
```

| Module | Rôle |
| --- | --- |
| `agents/agents/planner.py` | décompose l'objectif en DAG, répare le JSON invalide, repli heuristique |
| `agents/agents/worker.py` | exécute **une** tâche, avec boucle ReAct bornée |
| `agents/agents/critic.py` | note chaque résultat (0–1) et liste les problèmes |
| `agents/agents/synthesizer.py` | compose la réponse finale, signale les échecs |
| `agents/orchestrator.py` | ordonnancement asyncio, timeouts, retries, révisions, budget |
| `agents/council.py` | conseil multi-modèles : propositions, critique anonymisée, juge |
| `agents/core/registry.py` | outils : validation de schéma, timeout, sortie bornée |
| `agents/core/budget.py` | plafonds de tokens, d'appels et de durée |
| `agents/core/llm.py` | protocole provider, factory, retries exponentiels |
| `agents/core/providers/` | `mock` (hors ligne), `scripted` (tests), OpenAI, Anthropic, Gemini |
| `agents/tools/` | calcul, recherche BM25, fichiers sandboxés, texte |
| `agents/data/corpus/` | corpus documentaire d'exemple, embarqué dans le paquet |
| `agents/cli.py` | `run`, `council`, `plan`, `tools`, `providers` + codes de sortie stables |

## Démarrage rapide

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 1. aperçu du plan sans exécuter
python -m agents plan "Auditer la sécurité des outils"

# 2. exécution complète (provider mock : aucun réseau, aucune clé)
python -m agents run "Combien coûtent 12 x 249,99 USD ?" --verbose

# 3. rapport JSON + trace d'événements
python -m agents run "Combien coûtent 12 x 249,99 USD ?" --json runs/rapport.json --trace runs/trace.jsonl
```

Avec `pip install -e .`, la commande `agents` remplace `python -m agents`.

## Brancher un vrai modèle

```bash
export OPENAI_API_KEY=sk-...
python -m agents run "Résume la documentation du projet" --provider openai:gpt-4o-mini

export ANTHROPIC_API_KEY=sk-ant-...
python -m agents run "Résume la documentation du projet" --provider anthropic

export GEMINI_API_KEY=AIza...            # ou GOOGLE_API_KEY
python -m agents run "Résume la documentation du projet" --provider gemini:gemini-2.0-flash
```

`python -m agents providers` indique quelles clés sont présentes. Aucune clé
n'est jamais écrite dans le code : lecture d'environnement uniquement.

## Utilisation comme bibliothèque

```python
import asyncio

from agents import Orchestrator, RunConfig
from agents.core.llm import build_provider
from agents.tools import build_registry

orchestrator = Orchestrator(
    provider=build_provider("mock"),  # ou "openai:gpt-4o-mini"
    registry=build_registry(workspace=".", corpus_dir="agents/data/corpus"),
    config=RunConfig(concurrency=4, task_timeout_s=30),
)
report = asyncio.run(orchestrator.run("Quel est le coût de 12 x 249,99 USD ?"))

print(report.status, report.usage.total_tokens)
for result in report.results:
    print(result.task_id, result.status, result.review.score if result.review else None)
print(report.final_answer)
```

## CLI

| Commande | Effet | Code de sortie |
| --- | --- | --- |
| `agents run "objectif"` | pipeline complet | `0` réussi, `3` partiel, `1` échec |
| `agents council "question"` | conseil multi-modèles + juge | `0` réussi, `3` partiel, `1` échec |
| `agents plan "objectif"` | plan seul (`--offline` pour l'heuristique) | `0` |
| `agents tools` | liste les outils et leurs schémas | `0` |
| `agents providers` | état des providers et des clés | `0` |
| — | erreur d'usage ou de configuration | `2` |
| — | interruption clavier | `130` |

Options principales de `run` : `--provider`, `--concurrency`, `--max-steps`,
`--task-timeout`, `--run-timeout`, `--max-attempts`, `--max-tokens`,
`--max-llm-calls`, `--max-seconds`, `--revise-below`, `--no-revise`,
`--workspace`, `--corpus`, `--json`, `--trace`, `--quiet`, `--verbose`.

## Outils exposés

| Outil | Description | Garde-fou |
| --- | --- | --- |
| `calc_evaluate` | arithmétique (`+ - * / // % **`, `sqrt`, `log`, `round`…) | évaluateur AST, **jamais `eval()`**, exposants plafonnés |
| `doc_search` | recherche BM25 dans le corpus local, avec extraits sources | requête non vide, `top_k` ≤ 10 |
| `file_read` / `file_list` | lecture et exploration du workspace | sandbox : chemins absolus et `..` refusés, taille plafonnée |
| `file_write` | écriture (désactivée par défaut) | activation explicite `--allow-write` |
| `text_stats` / `text_summarize` | statistiques et résumé extractif | entrées bornées, aucun appel LLM |

## Choix de conception (et ce qu'ils évitent)

- **Budget obligatoire** (`agents/core/budget.py`) — un run multi-agents peut
  s'emballer entre boucles ReAct, retries et parallélisme. Les plafonds de
  tokens, d'appels et de durée sont consommés à chaque appel et lèvent
  `BudgetExceeded` **avant** que la facture ne dérive.
- **Aucun `eval()`** (`agents/tools/calc.py`) — le calcul passe par un
  évaluateur AST à liste blanche. `__import__`, attributs, lambdas et
  compréhensions sont rejetés, ce qui neutralise l'injection de code par le
  modèle.
- **Sandbox fichiers** (`agents/tools/files.py`) — la vérification
  d'appartenance a lieu **après** `Path.resolve()`, donc un lien symbolique vers
  `/etc` est refusé. L'écriture est opt-in.
- **Pannes isolées** (`agents/orchestrator.py`) — une tâche en échec marque ses
  dépendantes `blocked` sans annuler les autres branches du DAG. Budget épuisé
  ou timeout global produisent un **rapport partiel** exploitable.
- **Zéro confiance dans le LLM** — JSON du planner extrait par équilibrage
  d'accolades (`agents/core/jsonio.py`) avec réparation puis repli heuristique ;
  verdicts du critique bornés à [0, 1] ; toute erreur d'outil est renvoyée au
  modèle comme observation `ERREUR: ...` pour qu'il se corrige.
- **Attente des dépendances hors du sémaphore** — sinon un plan en chaîne
  s'auto-bloquerait : c'est le piège classique des orchestrateurs concurrents.
- **Traces structurées** — événements JSONL (`--trace`) horodatés, réutilisables
  pour du débogage ou de l'observabilité.

## Tests et qualité

```bash
pytest                     # 258 tests, ~1,9 s, aucun réseau requis
pytest -m live             # providers réels (clé API nécessaire)
pytest --cov=agents        # couverture : 90 %
ruff check . && ruff format --check .
```

La CI (`.github/workflows/`) exécute lint + tests sur Python 3.11, 3.12 et 3.13.
Les points les plus testés sont ceux qui coûtent cher en production : refus
d'exécution de code arbitraire, évasion de sandbox, validation d'arguments,
détection de cycle dans le plan, dépassement de budget, parallélisme effectif
et reprise après échec.

## Limites connues

- Le provider `mock` est déterministe et **ne comprend pas** le langage : il sert
  à exécuter le pipeline hors ligne. La qualité réelle dépend du modèle branché.
- Le critique est un **unique passage**, sans débat entre plusieurs juges : un
  score élevé ne garantit pas l'absence d'hallucination.
- Les sorties de dépendances transmises aux workers sont tronquées à 1200
  caractères ; sur un plan très large, il faut découper l'objectif.
- Aucune persistance : les runs ne sont pas rejouables depuis un stockage.
- Les providers OpenAI/Anthropic/Gemini sont couverts par des tests de conversion,
  mais le chemin HTTP reste vérifié uniquement en `pytest -m live`.

## Feuille de route

- persistance SQLite des runs et reprise après interruption ;
- passerelle « conseil comme agent » : un siège du conseil utilisable comme worker de l'orchestrateur ;
- export OpenTelemetry des traces ;
- jeu d'évaluation automatique des plans sur des objectifs de référence.

## Licence

MIT — voir `LICENSE`.
