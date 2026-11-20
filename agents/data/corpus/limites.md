# Limites connues et pistes d'amelioration

Le provider mock est deterministe et ne comprend pas reellement le langage : il
sert a executer le pipeline hors ligne, sans cle API et sans cout. La qualite
d'une reponse reelle depend donc du modele branche via --provider.

Le critique est un unique passage, sans debat entre plusieurs juges. Un score
eleve ne garantit pas l'absence d'hallucination : il indique seulement qu'un
modele a juge le resultat coherent avec l'instruction.

Les resultats de taches sont transmis aux dependances tronques a 1200
caracteres, pour contenir la taille du contexte. Sur un plan tres large, cette
troncature peut perdre une information utile : il faut alors decouper l'objectif
en plusieurs runs.

Pistes envisagees : persistance des runs dans SQLite, reprise apres interruption,
evaluation automatique par jeu de tests, et export des traces au format OpenTelemetry.
