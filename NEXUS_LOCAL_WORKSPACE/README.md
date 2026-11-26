# Espace de pilotage — NEXUS AI (projet local)

> **Périmètre : documentation et gouvernance uniquement.** Le code source principal de NEXUS AI reste sur l'ordinateur du propriétaire. Ce dossier ne le copie pas, ne le déplace pas et ne le remplace pas.

## Pourquoi cet espace existe

Cet espace sert à suivre séparément le projet local **NEXUS AI**, ses décisions, ses audits, ses sauvegardes, ses risques et ses validations. Il ne constitue pas le dépôt du code source de NEXUS.

## Distinction impérative

- **NEXUS AI local** : projet principal situé sur l'ordinateur du propriétaire. Son chemin exact, sa structure et son état doivent être confirmés depuis cette machine.
- **05 STUDIO local** : projet distinct. Il conserve son propre code, ses sauvegardes, ses audits et son cycle de validation.
- **Dépôt GitHub courant** : dépôt public de support. Il héberge cet espace documentaire, pas le code local de NEXUS.
- **Dossier `nexus/` déjà présent à la racine** : composant existant décrit dans le README racine comme « Nexus HLP.AI — génération vidéo multi-modèles ». Il ne doit pas être confondu avec le projet NEXUS AI local ni être modifié au titre de cet espace.

## Règles non négociables

1. Aucune fusion entre NEXUS AI et 05 STUDIO.
2. Aucune modification du code local à partir de cette documentation seule.
3. Avant toute modification : diagnostic, sauvegarde vérifiée, proposition de changement, tests et validation humaine explicite.
4. Aucun secret, mot de passe, jeton, clé API, fichier .env, donnée personnelle ou sauvegarde privée dans ce dépôt public.
5. Toute information inconnue est marquée **À CONFIRMER** ; ne pas inventer l'architecture ou l'état du projet.
6. Les corrections sont petites, traçables, réversibles et testées.
7. Un échec de test ou une sauvegarde non vérifiée bloque la mise en production.

## Documents

- [Inventaire du projet](PROJECT_INVENTORY.md)
- [Politique de sécurité](SECURITY_POLICY.md)
- [Sauvegarde et restauration](BACKUP_AND_RESTORE.md)
- [Contrôle des changements et validation](CHANGE_CONTROL.md)
- [Modèle de rapport d'audit](AUDIT_TEMPLATE.md)
- [Feuille de route](ROADMAP.md)

## État initial

- Emplacement du code local : **À CONFIRMER sur l'ordinateur**
- Version/commit local : **À CONFIRMER**
- Langages, dépendances et architecture : **À INVENTORIER**
- Tests et état CI : **À VÉRIFIER**
- Dernière sauvegarde restaurable : **À VÉRIFIER**
- Propriétaire des approbations : propriétaire du projet

## Première étape requise

Depuis l'ordinateur qui contient NEXUS AI, fournir un inventaire non sensible du dossier (arborescence, fichiers de configuration sans secrets, instructions de lancement et résultats des tests). Cet inventaire permettra de compléter les documents sans supposer ni réécrire le projet.
