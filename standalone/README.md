# Fichier autonome pour VS Code

`council_chat.py` tient dans **un seul fichier** et n'a aucune dépendance
externe. Copiez-le dans VS Code, puis :

```bash
python council_chat.py "Votre question"
# ou, en mode interactif
python council_chat.py
```

Sans clé, les trois sièges sont simulés. Pour interroger les vraies API,
définissez `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` et/ou `GEMINI_API_KEY` dans le
terminal avant de lancer le script. Une clé manquante fait simplement basculer
le siège concerné en simulation.

Le fichier n'enregistre aucune clé et utilise seulement `urllib` de la
bibliothèque standard.
