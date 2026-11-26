# Contrôle des changements — NEXUS AI

## Principe d'approbation

Aucune modification du code local, de la configuration, des dépendances, des données, des accès ou du déploiement n'est autorisée sur la seule base d'une proposition technique. Le propriétaire doit approuver explicitement le changement précis avant son application.

## Cycle obligatoire

1. **Demande** — décrire le problème, le résultat attendu et le périmètre.
2. **Diagnostic** — examiner les fichiers concernés, les dépendances et les impacts.
3. **Plan** — proposer un diff ciblé, les risques et les tests.
4. **Sauvegarde** — créer et vérifier une sauvegarde restaurable.
5. **Approbation** — obtenir l'accord explicite du propriétaire sur cette intervention.
6. **Implémentation** — appliquer uniquement le périmètre approuvé, idéalement sur une branche dédiée.
7. **Vérification** — tests, lint, analyse de sécurité et revue du diff.
8. **Présentation** — fournir les fichiers modifiés, résultats, limites et risques résiduels.
9. **Décision** — le propriétaire accepte ou refuse l'intégration.
10. **Retour arrière** — restaurer la version précédente si les critères échouent.

## Critères de blocage

Ne pas poursuivre si :

- la sauvegarde est absente ou non vérifiée ;
- le périmètre du changement est ambigu ;
- un test critique échoue ;
- un secret apparaît dans le diff ;
- une dépendance ou une permission inattendue est ajoutée ;
- l'effet sur 05 STUDIO ou un autre projet n'est pas compris ;
- l'approbation explicite manque.

## Modèle de demande de validation

- Projet : NEXUS AI
- Référence / branche :
- Problème :
- Fichiers concernés :
- Résumé du changement :
- Risques et effets secondaires :
- Sauvegarde vérifiée :
- Tests prévus :
- Résultats des tests :
- Retour arrière :
- Décision du propriétaire : EN ATTENTE / APPROUVÉ / REFUSÉ

Une approbation vaut uniquement pour le changement décrit. Toute extension de périmètre nécessite une nouvelle validation.
