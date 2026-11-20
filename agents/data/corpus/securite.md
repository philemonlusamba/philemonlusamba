# Securite des outils

Les outils sont la surface d'attaque principale d'un systeme d'agents. Trois
regles sont appliquees sans exception.

Premierement, le calcul arithmetique n'utilise jamais eval(). L'evaluateur
parcourt l'AST Python et n'accepte qu'une liste blanche de noeuds : additions,
soustractions, multiplications, divisions, puissances, et quelques fonctions
mathematiques. La profondeur et la longueur des expressions sont bornees, et les
exposants sont plafonnes pour eviter un deni de service.

Deuxiemement, l'acces aux fichiers est sandboxe. Tout chemin est resolu puis
verifie : les chemins absolus et les sorties de repertoire par .. sont refuses,
y compris via des liens symboliques, car la verification a lieu apres resolve().
L'ecriture est desactivee par defaut et doit etre activee explicitement.

Troisiemement, les arguments d'outils sont valides contre un schema JSON avant
execution. Une cle inconnue est rejetee plutot qu'ignoree, chaque appel a un
timeout, et la sortie est tronquee pour ne pas saturer le contexte du modele.
Aucun outil n'execute de commande shell.
