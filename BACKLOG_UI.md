# Backlog — repéré pendant le chantier UI, délibérément NON fait

Ce fichier existe pour tenir la règle anti-dérive : ce qui n'est pas de l'interface
n'est pas traité dans un tour d'interface. Rien ci-dessous n'a été modifié.

## Hors périmètre — moteur et tests

- **La suite de tests reste lente.** Les tests marqués `reel` manipulent 16,5 M de
  lignes de carnet et prennent plusieurs minutes chacun ; un `pytest` par défaut ne
  peut donc pas servir de garde-fou rapide. Piste : séparer le marqueur `reel` du
  cycle court. Non fait — hors interface.

- **Deux wallets de tête ont un intervalle de crédibilité nul.** Les rangs 1 et 2
  affichent `IC [100, 100]`, largeur 0 : la transformation du score sature au
  plafond, si bien que les mors se referment complètement et que le dispositif
  visuel n'a plus rien à montrer. Ce n'est pas un défaut d'affichage — l'interface
  rend fidèlement ce que le modèle produit. Toucher à la saturation serait modifier
  le score. Non fait, et à ne pas faire sans décision explicite.

- **Beaucoup de wallets à probabilité calibrée nulle.** Le nuage score-contre-
  probabilité montre une bande dense à `conf = 0`. C'est peut-être une propriété
  réelle de la population, peut-être un effet de la calibration. Question
  scientifique, pas question d'interface.

## Interface — améliorations possibles, non nécessaires à l'usage

- **Thème clair.** La direction retenue est un registre unique sombre, assumé : une
  face-avant d'instrument n'a pas de mode clair. Le juge du panel a néanmoins fourni
  une palette papier complète et cohérente. À reprendre si le besoin apparaît.

- **Animation d'entrée de l'index.** Le balayage de l'aiguille de 0 vers sa position
  était prévu par la direction ; il est écarté pour l'instant, 231 cartes animées au
  défilement coûtant plus qu'elles n'apportent. `prefers-reduced-motion` est déjà
  respecté partout.

- **Les libellés d'indicateur se tronquent sous 340 px** (« WALLETS CLAS… »). Les
  valeurs, elles, restent entières. Acceptable : on tronque l'étiquette, jamais la
  mesure.
