# Nexus HLP.AI

**Nexus HLP.AI** réunit les principales familles de génération vidéo dans une
interface unique : Sora, Veo, Runway, Kling, Luma, Pika, Hailuo, Firefly,
Seedance, Stable Video, Wan, HunyuanVideo, CogVideoX, Mochi et les workflows
ComfyUI.

> Important : « réunir » signifie **cataloguer et router**. Nexus ne contourne
> ni abonnement, ni liste d'attente, ni conditions d'utilisation. Une famille
> visible n'est réellement appelée que lorsqu'un connecteur autorisé est
> configuré côté serveur.

## Lancer immédiatement

Aucune installation n'est nécessaire pour la démo :

```bash
python -m nexus.server --port 8001
```

Ouvrez <http://localhost:8001>. Le mode `Nexus Demo` produit un aperçu animé et
peut l'exporter en **vidéo WebM directement dans le navigateur**. Il n'appelle
aucune IA réelle et ne génère aucun coût.

## Fonctionnalités

- studio texte-vers-vidéo et image-vers-vidéo (URL d'image) ;
- catalogue de 15 familles commerciales, ouvertes et locales ;
- choix du format, de la durée, de la résolution, du style, du seed et du
  prompt négatif ;
- file de générations, progression, annulation, historique persistant local ;
- aperçu animé hors ligne et export WebM côté navigateur ;
- connecteurs serveur Replicate, fal.ai et webhook Nexus ;
- routage `auto` avec repli explicite sur la démo ;
- aucune clé envoyée au navigateur ou écrite dans l'historique ;
- API JSON testable, serveur sans framework et conteneur Docker dédié.

## Connecter de vraies générations

### Replicate

```bash
export REPLICATE_API_TOKEN=r8_...
# facultatif : modèle utilisé quand le formulaire reste en Nexus Auto
export NEXUS_REPLICATE_MODEL=owner/model
python -m nexus.server
```

Dans les réglages avancés, choisissez `Replicate` et indiquez une référence
`owner/model`. Les champs acceptés peuvent varier selon le modèle : vérifiez sa
fiche API.

### fal.ai

```bash
export FAL_KEY=...
export NEXUS_FAL_MODEL=fal-ai/nom-du-modele
python -m nexus.server
```

Dans les réglages avancés, choisissez `fal.ai` et indiquez son identifiant de
modèle.

### Webhook universel

Le webhook permet d'ajouter Sora, Veo, Runway, Kling, un workflow ComfyUI ou un
proxy interne sans modifier l'interface :

```bash
export NEXUS_WEBHOOK_URL=https://votre-api.example/generate
export NEXUS_WEBHOOK_TOKEN=secret-facultatif
python -m nexus.server
```

Nexus envoie :

```json
{
  "type": "video.generate",
  "request": {
    "prompt": "...",
    "engine": "sora",
    "aspect_ratio": "16:9",
    "duration": 5,
    "resolution": "720p"
  }
}
```

Réponse immédiate :

```json
{"video_url": "https://cdn.example/video.mp4"}
```

Ou réponse asynchrone :

```json
{"id": "job-123", "status_url": "https://api.example/jobs/123"}
```

L'URL de statut doit renvoyer `status`, éventuellement `progress`, puis
`video_url` quand le statut est `completed`.

## API locale

```bash
curl http://localhost:8001/api/health
curl http://localhost:8001/api/catalog

curl -X POST http://localhost:8001/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "Kinshasa futuriste sous la pluie néon",
    "engine": "sora",
    "connector": "demo",
    "aspect_ratio": "16:9",
    "duration": 5,
    "resolution": "720p",
    "style": "cinematic"
  }'
```

Routes :

| Méthode | Route | Effet |
| --- | --- | --- |
| `GET` | `/api/health` | santé, version et statistiques |
| `GET` | `/api/catalog` | moteurs et état public des connecteurs |
| `GET` | `/api/jobs` | historique et progression |
| `POST` | `/api/jobs` | nouvelle génération |
| `GET` | `/api/jobs/{id}` | génération individuelle |
| `POST` | `/api/jobs/{id}/cancel` | annulation locale |
| `DELETE` | `/api/jobs/{id}` | suppression d'un job terminé |
| `GET` | `/api/jobs/{id}/preview.svg` | aperçu animé de démo |

## Déploiement Docker

```bash
docker build -f Dockerfile.nexus -t nexus-hlp-ai .
docker run --rm -p 8001:8001 nexus-hlp-ai
```

La variable `PORT` est respectée par le serveur. Placez les clés dans le coffre
de secrets de l'hébergeur, jamais dans l'image ou le dépôt.

## Sécurité et limites

- les secrets sont lus exclusivement dans l'environnement du serveur ;
- les URL de webhook viennent de l'environnement, pas du navigateur, pour
  éviter un proxy SSRF arbitraire ;
- les requêtes, tailles et valeurs sont bornées ;
- l'historique `runs/nexus_jobs.json` ne contient aucune clé ;
- l'annulation Nexus n'annule pas nécessairement la facturation déjà engagée
  chez un fournisseur externe ;
- les noms, versions, tarifs et limites des modèles tiers évoluent : vérifiez
  toujours leur documentation et leurs conditions officielles ;
- le mode démo est une animation locale clairement étiquetée, pas une sortie
  d'un modèle d'intelligence artificielle.
