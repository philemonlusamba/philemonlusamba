# Feuille de route — NEXUS AI local

Cette feuille de route est un ordre de travail proposé. Elle ne signifie pas que les tâches sont déjà réalisées.

## Phase 0 — Accès et inventaire

- [ ] Confirmer le chemin local et la version du projet.
- [ ] Collecter l'arborescence et les fichiers de configuration non sensibles.
- [ ] Identifier le runtime, les dépendances, les points d'entrée et les données.
- [ ] Cartographier les frontières avec 05 STUDIO.
- [ ] Établir l'état initial des tests et de la CI.

**Critère de sortie :** inventaire validé par le propriétaire.

## Phase 1 — Fiabilité et sauvegardes

- [ ] Documenter la procédure de lancement et d'arrêt.
- [ ] Mettre en place des sauvegardes séparées et chiffrées si nécessaire.
- [ ] Tester une restauration dans un emplacement isolé.
- [ ] Identifier les contrôles de santé et fonctions critiques.

**Critère de sortie :** sauvegarde restaurable démontrée.

## Phase 2 — Qualité et sécurité

- [ ] Exécuter la suite de tests existante.
- [ ] Ajouter les tests de non-régression manquants.
- [ ] Activer lint, format et analyse statique adaptés au projet.
- [ ] Examiner secrets, dépendances, permissions, entrées et appels réseau.
- [ ] Prioriser les constats par risque démontré.

**Critère de sortie :** rapport d'audit avec preuves et plan de correction.

## Phase 3 — CI et gouvernance

- [ ] Vérifier les workflows existants avant toute modification.
- [ ] Exécuter les contrôles sur les branches de travail.
- [ ] Exiger une revue humaine avant fusion.
- [ ] Prévoir les artefacts de test et rapports non sensibles.
- [ ] Documenter les procédures de retour arrière.

**Critère de sortie :** pipeline reproductible et contrôles de fusion vérifiés.

## Phase 4 — Évolution fonctionnelle

- [ ] Construire une feuille de route à partir des besoins confirmés.
- [ ] Évaluer les nouvelles fonctions avec analyse coût/risque.
- [ ] Mesurer performance, fiabilité, confidentialité et coûts.
- [ ] Livrer par changements limités, testés et approuvés.

## Dépendances et blocages

Le code local n'étant pas présent dans ce dépôt, aucune phase technique ne doit être déclarée terminée avant examen des fichiers depuis l'ordinateur du propriétaire.
