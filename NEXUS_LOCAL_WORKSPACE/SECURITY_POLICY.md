# Politique minimale de sécurité — NEXUS AI

Cette politique est un socle de gouvernance. Elle ne prétend pas certifier le niveau de sécurité du code local, qui n'a pas encore été inspecté.

## Protection des secrets

- Ne jamais committer de clés API, jetons, mots de passe, certificats privés, fichiers `.env`, cookies ou clés SSH.
- Utiliser des variables d'environnement ou un gestionnaire de secrets adapté.
- Fournir uniquement un fichier `.env.example` avec des noms et valeurs factices.
- En cas de fuite : révoquer/faire tourner le secret, examiner les journaux et documenter l'incident.

## Dépendances et chaîne d'approvisionnement

- Épingler les versions et conserver un fichier de verrouillage lorsque l'écosystème le permet.
- Examiner les mises à jour et les avis de vulnérabilité avant adoption.
- Éviter les dépendances inutilisées ou non maintenues.
- Exécuter les contrôles de dépendances sur une branche de travail, puis examiner les résultats.

## Code et exécution

- Valider les entrées externes et appliquer le principe du moindre privilège.
- Ne pas exécuter de commandes générées par un modèle sans validation et sandbox appropriées.
- Limiter les accès fichiers, réseau, processus et outils au strict nécessaire.
- Ne pas journaliser les secrets ni les données personnelles sensibles.
- Prévoir des limites de taille, de durée, de débit et de coût pour les opérations exposées.

## Accès et données

- Utiliser des comptes individuels et l'authentification multifacteur lorsque disponible.
- Accorder uniquement les permissions nécessaires.
- Séparer développement, test et production.
- Chiffrer les sauvegardes et protéger leurs accès.
- Définir la conservation et la suppression des données.

## Contrôles avant livraison

- [ ] Tests automatisés réussis
- [ ] Lint / format / analyse statique réussis
- [ ] Analyse des dépendances examinée
- [ ] Aucun secret détecté dans le diff
- [ ] Permissions et nouvelles surfaces réseau examinées
- [ ] Journalisation sans fuite de données
- [ ] Sauvegarde récente et restaurable
- [ ] Retour arrière documenté
- [ ] Validation humaine explicite

## Gestion d'incident

1. Suspendre le déploiement ou l'action risquée.
2. Préserver les journaux utiles sans exposer de secrets.
3. Isoler le composant concerné si nécessaire.
4. Révoquer les identifiants compromis.
5. Restaurer une version connue comme saine si nécessaire.
6. Documenter cause, impact, correction et prévention.
