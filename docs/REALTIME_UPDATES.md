# Suivi du daily en temps réel

> État : implémenté le 29 juin 2026.
>
> Le site et l'Activity affichent simultanément le classement du mode courant,
> le jeu et la progression des participants sur les trois modes.

## Expérience

Sur grand écran, la page utilise trois zones stables :

1. le classement complet du mode courant à gauche ;
2. le jeu au centre ;
3. tous les participants du daily à droite.

Le panneau de droite affiche l'avatar, le nom et trois statuts :

| Statut | Signification |
|---|---|
| `✓` vert | mode réussi ; |
| `×` rouge | mode raté ; |
| sablier jaune | partie en cours ; |
| `✓` gris | mode terminé, résultat encore masqué ; |
| tiret | mode non commencé. |

Les joueurs actifs sont placés en premier. Sur un écran plus étroit, les panneaux
latéraux passent sous le jeu afin de conserver une largeur correcte pour les
propositions.

## Anti-spoil

Le payload live est construit pour chaque observateur.

- Tant que l'observateur n'a pas terminé un mode, les résultats terminés des autres
  sont envoyés avec le statut neutre `complete`.
- Dès qu'il termine ce même mode, les statuts deviennent `win` ou `fail`.
- Le flux de progression ne contient jamais `guessed_id`, `correct_id`, le texte
  d'une proposition ou le contenu de la bonne réponse.
- Le classement détaillé et les anciennes données de résultat du mode courant
  restent verrouillés jusqu'à ce que l'observateur ait répondu.

La protection est appliquée côté serveur. Masquer uniquement les éléments en CSS ou
JavaScript ne serait pas suffisant, car les données resteraient visibles dans le
réseau ou le code source.

## Présence

`POST /daily/presence` et son alias `/.proxy/daily/presence` reçoivent un heartbeat
signé toutes les 15 secondes.

- Une présence expire après 45 secondes sans heartbeat.
- Une ouverture de page marque le mode consulté.
- `POST /daily/start` marque le mode comme en cours.
- `POST /daily/answer` marque le mode comme terminé.
- Les tentatives terminées viennent de SQLite et restent donc visibles après un
  redémarrage ; seule la présence instantanée est conservée en mémoire.

Le serveur envoie aussi un snapshot SSE toutes les 15 secondes. Cela retire les
présences expirées même lorsqu'aucune nouvelle réponse n'a été enregistrée.

## Transport

Le transport principal reste Server-Sent Events :

```text
GET /daily/stream?t=<token>
GET /.proxy/daily/stream?t=<token>
```

La clé du broker est désormais `(guild_id, date)`. Un démarrage ou une réponse dans
n'importe lequel des trois modes réveille donc tous les viewers du daily.

Chaque signal provoque un recalcul personnalisé :

```json
{
  "unlocked": false,
  "results": [],
  "leaderboard": [],
  "participant_count": 3,
  "progress": [
    {
      "user_id": "123",
      "name": "Joueur",
      "avatar_url": "https://...",
      "active": true,
      "playing": true,
      "activity": "Devine la phrase en cours",
      "statuses": {
        "author": "complete",
        "phrase": "playing",
        "media": "waiting"
      },
      "is_me": false
    }
  ]
}
```

Quand le viewer a terminé le mode courant, `unlocked` passe à `true` et les champs
`results` et `leaderboard` sont également remplis.

## Fallback

Si le proxy Discord bufferise ou bloque le SSE, le client bascule automatiquement
sur :

```text
GET /daily/state?t=<token>
GET /.proxy/daily/state?t=<token>
```

Le polling a lieu toutes les trois secondes, s'arrête lorsque la page est masquée et
reprend lorsqu'elle redevient visible.

## Contraintes d'exploitation

- Le broker et la présence sont en mémoire : le déploiement doit rester mono-process.
- Waitress réserve un thread par connexion SSE. `WEBAPP_THREADS=64` convient à un
  groupe d'amis, pas à un service public de grande taille.
- Le bot et Flask restent dans le même process, car `/daily/context` utilise la loop
  Discord du bot.
- Un passage futur en multi-worker nécessiterait un stockage partagé, par exemple
  Redis pour le pub/sub et les présences.

## Événements publiés

Un signal global `(guild_id, date)` est publié après :

- une nouvelle présence visible ou un changement de mode ;
- le clic sur **Jouer** ;
- l'enregistrement d'une réponse ;
- une correction administrateur.

Les simples heartbeats renouvellent la date d'expiration sans réveiller tout le
monde.

La page reçoit aussi un premier état personnalisé dans `window.DAILY` au rendu.
La colonne En direct est donc remplie immédiatement ; le SSE prend ensuite le relais
sans modifier les règles anti-spoil.

## Tests

`tests/test_realtime_updates.py` vérifie notamment :

- l'accès au flux avant d'avoir répondu, avec résultats et classement verrouillés ;
- le masquage d'une victoire ou d'une défaite avant la réponse du viewer ;
- la révélation après avoir terminé le même mode ;
- le statut « en cours » après `/daily/start` ;
- l'expiration d'une présence devenue silencieuse ;
- l'indépendance de l'anti-spoil pour chacun des trois modes ;
- l'absence des identifiants de réponse dans le payload protégé ;
- la publication commune aux trois modes ;
- le désabonnement du flux lors de la fermeture.
- l'état initial anti-spoil inclus dans la page avant la connexion SSE.

Commande :

```bash
python -m unittest tests.test_realtime_updates -v
```

## Validation après déploiement

1. Ouvrir l'Activity avec deux comptes sur le même serveur.
2. Commencer des modes différents.
3. Vérifier que les deux sabliers apparaissent sans rechargement.
4. Terminer un mode avec le premier compte.
5. Vérifier que le second voit un résultat gris tant qu'il n'a pas joué ce mode.
6. Terminer le même mode avec le second compte et vérifier que les résultats réels
   deviennent visibles.
7. Fermer un compte et vérifier sa disparition des joueurs actifs après environ une
   minute.
