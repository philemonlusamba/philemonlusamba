# Application web du conseil

Interface locale pour faire collaborer **ChatGPT, Claude et Gemini** :

1. propositions indépendantes ;
2. critique croisée avec réponses anonymisées ;
3. synthèse d'un juge (`Consensus`, `Divergences`, `Réponse finale`, `Confiance`).

## Lancer immédiatement

Depuis la racine du dépôt :

```bash
python app/server.py
```

Ouvrir <http://localhost:8000>. Sans clé API, l'application utilise trois
simulateurs déterministes : l'interface fonctionne donc immédiatement, sans
réseau, sans installation et sans coût.

## Activer les vrais modèles

Les clients réels utilisent la dépendance optionnelle `httpx` :

```bash
python -m venv .venv
source .venv/bin/activate               # Windows : .venv\Scripts\activate
pip install -e ".[providers]"

export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=AIza...            # ou GOOGLE_API_KEY
python app/server.py
```

Une clé absente ne bloque pas les autres sièges : son siège reste simulé. Les
clés sont lues uniquement depuis l'environnement et ne sont jamais transmises
au navigateur ni enregistrées par l'application.

Variables facultatives : `AGENTS_OPENAI_MODEL`, `AGENTS_ANTHROPIC_MODEL`,
`AGENTS_GEMINI_MODEL` et les URL de base décrites dans `.env.example`.

## API locale

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/council \
  -H 'Content-Type: application/json' \
  -d '{"question":"Faut-il un index SQL ?","rounds":2}'
```

Le serveur utilise uniquement la bibliothèque standard de Python. Le moteur de
délibération reste celui de `agents/council.py`.

## Conteneur et hébergement

Le `Dockerfile` à la racine permet de déployer la même application sur un
hébergeur compatible Docker. Le serveur écoute `0.0.0.0` et respecte la
variable `PORT` fournie par la plateforme :

```bash
docker build -t multitask-agents .
docker run --rm -p 8000:8000 multitask-agents
```

Ajoutez les clés API comme variables secrètes de l'hébergeur, jamais comme
arguments du build ni dans le dépôt.
