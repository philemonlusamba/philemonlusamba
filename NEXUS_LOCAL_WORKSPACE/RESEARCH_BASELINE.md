# Référentiel de recherche — exigences à évaluer pour NEXUS AI

> Document de recherche et de conception. Il ne décrit pas des fonctions déjà implémentées. Toute intégration dans le code local nécessite l'inventaire du projet, une proposition de conception, une sauvegarde, des tests et l'approbation explicite du propriétaire.

Date de revue : 2026-11-26.

## Sources de référence

- OWASP GenAI / LLM Top 10 2026 : https://github.com/GenAI-Security-Project/GenAI-LLM-Top10
- NIST AI RMF et profil Generative AI NIST AI 600-1 : https://www.nist.gov/itl/ai-risk-management-framework
- NIST Secure Software Development Framework (SSDF) SP 800-218 : https://csrc.nist.gov/Projects/ssdf
- OpenTelemetry Semantic Conventions : https://opentelemetry.io/docs/concepts/semantic-conventions/

## Exigences candidates à vérifier contre l'architecture réelle

### 1. Sécurité IA et agents

- Défense contre l'injection de prompt directe et indirecte ; traiter documents, pages web, courriels et résultats d'outils comme données non fiables.
- Vérifier et borner toutes les sorties du modèle avant utilisation par un outil, un shell, une base de données ou une interface.
- Autorisations minimales par outil, ressource, utilisateur et session.
- Confirmation humaine explicite avant actions externes, destructrices, financières, publication, changement d'accès ou modification de code.
- Limites de boucles d'agents, appels d'outils, durée, taille de contexte, tokens et coût.
- Cloisonnement des secrets, données privées, contextes de conversation et résultats de recherche.
- Registre et validation des modèles, outils, plugins, serveurs MCP, dépendances et sources de données.
- Protection contre l'empoisonnement des données, les fuites de contexte caché, la désinformation et les faiblesses de recherche vectorielle si RAG est utilisé.

### 2. Gouvernance et évaluation IA

Adopter une démarche inspirée du NIST AI RMF : gouverner, cartographier, mesurer et gérer les risques. Pour chaque fonction IA, documenter :
- objectif et utilisateurs concernés ;
- données d'entrée et de sortie ;
- dépendances et accès ;
- risques et gravité ;
- tests d'évaluation et seuils d'acceptation ;
- limites connues et procédure de recours humain.

### 3. Ingénierie logicielle sécurisée

Adopter les pratiques pertinentes du NIST SSDF :
- exigences de sécurité et décisions d'architecture documentées ;
- environnement de développement et de build protégé ;
- revue de code et contrôle des dépendances ;
- tests automatisés et analyse statique ;
- provenance et intégrité des composants et artefacts ;
- traitement documenté des vulnérabilités et incidents.

### 4. Observabilité

Évaluer OpenTelemetry pour standardiser traces, métriques et journaux si compatible avec la pile existante. Ne jamais journaliser les prompts privés, secrets ou données sensibles sans justification, minimisation et contrôle d'accès. Les identifiants de trace doivent permettre de diagnostiquer une action sans exposer son contenu confidentiel.

### 5. Fiabilité et reprise

- Tests unitaires, intégration, non-régression et tests de sécurité.
- Contrôles de santé et surveillance des erreurs.
- Timeouts, retries bornés, idempotence et circuit breakers pour les appels externes lorsque pertinents.
- Sauvegardes indépendantes, chiffrées si nécessaire, et restauration réellement testée.
- Versionnage, migrations contrôlées et procédure de retour arrière.

## Matrice de priorisation

| Priorité | Capacité à évaluer | Critère de validation |
|---|---|---|
| P0 | Contrôle humain et moindre privilège des outils | Aucune action sensible sans autorisation vérifiable |
| P0 | Protection des secrets et données | Aucun secret dans le dépôt, les logs ou les sorties |
| P0 | Injection de prompt et sorties non fiables | Jeux de tests adversariaux et validation des sorties |
| P0 | Sauvegarde/restauration | Restauration testée avant changements risqués |
| P1 | Tests, analyse statique et dépendances | CI reproductible et résultats consultables |
| P1 | Observabilité | Traces, métriques et logs minimisés et protégés |
| P1 | Provenance des modèles/outils | Versions, sources et permissions inventoriées |
| P2 | Évaluations qualité IA | Jeux de tests, critères et régressions mesurés |
| P2 | Résilience des services | Timeouts, limites, reprise et dégradation contrôlée |

## Étapes avant toute implémentation

1. Examiner l'arborescence et le code local de NEXUS AI.
2. Identifier les fonctions réellement présentes : modèles, outils, mémoire, RAG, API, stockage, interface et exécution.
3. Mapper chaque exigence ci-dessus à un composant existant ; marquer non applicable si justifié.
4. Établir les risques et les tests de référence.
5. Présenter un plan de modifications limitées, avec sauvegarde et retour arrière.
6. Obtenir l'approbation du propriétaire avant toute modification.
7. Implémenter et vérifier par étapes, puis consigner les preuves.

## Limites de cette recherche

Ce référentiel est un point de départ, pas une certification, un audit du code ou une garantie de sécurité. Les cadres et recommandations évoluent ; les versions officielles doivent être reconsultées avant une mise en œuvre.
