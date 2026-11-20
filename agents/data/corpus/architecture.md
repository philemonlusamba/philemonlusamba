# Architecture de l'orchestrateur multi-agents

Le pipeline comporte cinq roles. Le PLANNER transforme l'objectif en un graphe
acyclique oriente de taches (DAG). Les WORKERS executent chaque tache en
parallele des qu'une place est disponible dans le semaphore de concurrence. Le
CRITIC note chaque resultat entre 0 et 1 et propose des corrections. Le
SYNTHESIZER compose la reponse finale en citant les identifiants de taches.

Le parallelisme repose sur asyncio : chaque tache attend ses dependances via un
asyncio.Event, puis acquiert un jeton de semaphore. L'attente des dependances se
fait avant l'acquisition du semaphore, faute de quoi un plan en chaine
s'auto-bloquerait. La concurrence par defaut est de trois taches simultanees.

Le budget d'execution plafonne trois ressources : le nombre d'appels LLM, le
nombre de tokens et la duree totale. Il est consomme a chaque appel et leve une
erreur BudgetExceeded avant que la facture ne derive. Un run interrompu produit
un rapport partiel plutot qu'une exception.
