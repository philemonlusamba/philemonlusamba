# Sauvegarde et restauration — NEXUS AI local

## Objectif

Disposer de sauvegardes indépendantes et restaurables avant toute modification importante. Ce document ne crée ni ne déclenche de sauvegarde sur l'ordinateur.

## Stratégie recommandée

Appliquer une stratégie de type 3-2-1 lorsque les moyens le permettent :

- 3 copies des données importantes ;
- 2 supports ou systèmes distincts ;
- 1 copie hors site ou hors de l'appareil principal, protégée et chiffrée.

Conserver séparément les sauvegardes de NEXUS AI et de 05 STUDIO.

## Avant chaque changement

1. Identifier le chemin exact du projet et la version de départ.
2. Vérifier l'état Git et les modifications locales non commitées.
3. Créer une sauvegarde datée des fichiers nécessaires.
4. Vérifier l'intégrité de l'archive et sa taille.
5. Consigner l'emplacement sécurisé de la sauvegarde (sans publier de chemin privé ou de lien sensible).
6. Effectuer un test de restauration dans un répertoire temporaire distinct lorsque cela est possible.
7. Ne commencer le changement qu'après validation de la sauvegarde.

## Après chaque changement

- Conserver le diff et le commit associé.
- Exécuter les tests pertinents.
- Vérifier le démarrage et les fonctions critiques.
- Garder la sauvegarde précédente jusqu'à acceptation du changement.
- Documenter le résultat et la décision d'acceptation ou de retour arrière.

## Procédure de restauration

1. Arrêter proprement l'application concernée.
2. Identifier la sauvegarde validée à restaurer.
3. Restaurer dans un emplacement contrôlé, sans écraser immédiatement la copie actuelle.
4. Vérifier les fichiers, dépendances, permissions et migrations.
5. Exécuter les tests et le contrôle de démarrage.
6. Basculer vers la restauration seulement après vérification.
7. Consigner la date, la source, les contrôles et le résultat.

## Registre des sauvegardes

| Date | Projet | Version/source | Emplacement sécurisé | Intégrité | Restauration testée |
|---|---|---|---|---|---|
| À renseigner | NEXUS AI | À confirmer | Non publié ici | À vérifier | Non |
| À renseigner | 05 STUDIO | À confirmer | Non publié ici | À vérifier | Non |

Ne jamais placer une sauvegarde, une base de données, des données utilisateur ou un fichier de configuration secret dans ce dépôt public.
