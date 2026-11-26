# Inventaire technique — NEXUS AI local

Dernière mise à jour : initialisation documentaire. Les champs non vérifiés restent à confirmer.

## Identité et périmètre

| Élément | Valeur |
|---|---|
| Nom | NEXUS AI |
| Emplacement | Ordinateur du propriétaire — chemin exact à confirmer |
| Dépôt source | Local / distant à confirmer |
| Branche/version | À confirmer |
| Responsable des validations | Propriétaire |
| Projet associé mais séparé | 05 STUDIO |

## Inventaire à compléter

| Domaine | À relever | État |
|---|---|---|
| Système | OS, version, architecture | À confirmer |
| Runtime | Python/Node/autres, versions | À confirmer |
| Entrée | commande ou fichier de démarrage | À confirmer |
| Modules | dossiers et responsabilités | À inventorier |
| Dépendances | fichiers de verrouillage et versions | À inventorier |
| Configuration | noms des variables seulement, jamais leurs valeurs | À inventorier |
| Stockage | bases, fichiers, migrations | À confirmer |
| Réseau/API | services externes et flux de données | À confirmer |
| Sécurité | authentification, permissions, secrets | À auditer |
| Tests | commande, couverture, résultats | À exécuter |
| CI | workflow, déclencheurs, derniers résultats | À vérifier |
| Sauvegardes | emplacement, fréquence, restauration testée | À vérifier |
| Déploiement | cible, procédure, retour arrière | À confirmer |

## Fichiers de référence à examiner

- README et documentation du projet.
- `pyproject.toml`, `requirements*.txt`, `package*.json` ou équivalents.
- Configurations de tests et de lint.
- Workflows CI.
- Fichiers Docker / scripts de démarrage.
- Schémas de base de données et migrations.

Ne pas publier les fichiers contenant des secrets ou des données privées. Produire des extraits expurgés si nécessaire.

## Contrôle de séparation avec 05 STUDIO

- [ ] Répertoires distincts
- [ ] Environnements virtuels distincts
- [ ] Dépendances et fichiers de configuration distincts
- [ ] Dépôts/branches distincts si Git est utilisé
- [ ] Sauvegardes distinctes
- [ ] Tests et rapports d'audit distincts
- [ ] Aucun import ou partage de données non documenté

## Historique des relevés

| Date | Élément examiné | Résultat | Réalisé par |
|---|---|---|---|
| Initialisation | Aucun fichier local examiné | Inventaire en attente d'accès à la machine | Assistant |
