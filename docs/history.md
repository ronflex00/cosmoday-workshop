# Historique persistant

FastAPI enregistre les messages valides de `sentinel/telemetry`,
`sentinel/ai/vision` et `sentinel/ai/anomaly`, ainsi que les alertes automatiques
et celles créées par `POST /api/v1/alerts`. Les JSON conservent le timestamp
de la source ; le backend ajoute un identifiant et un horodatage UTC de réception.

Le message et son éventuelle alerte sont enregistrés dans une transaction avant
la mise à jour REST/WebSocket. Réessayer une écriture conserve le même identifiant
de réception et ne crée pas de doublon. Deux messages distincts reçus avec les
mêmes valeurs restent deux événements distincts.

## Base locale

Sans `DATABASE_URL`, le lanceur utilise `backend/data/sentinel.db`. Le dossier
et la table `sentinel_history` sont créés au démarrage. Le fichier, ses journaux
SQLite et les profils de configuration sont ignorés par Git.

Configuration dans `.env.local` pour le lanceur, ou `backend/.env` pour le
lancement manuel :

```dotenv
DATABASE_URL=sqlite:///data/sentinel.db
```

Les chemins SQLite relatifs sont résolus à partir de `backend/`, quel que soit
le dossier de lancement. L'historique en base n'est pas limité à 120 points.
Le cache du dashboard recharge les dernières télémétries et les derniers
résultats d'anomalie (120 au maximum), la dernière vision et les 50 dernières
alertes. Les anciens résultats restent accessibles par pagination.

Le broker doit se reconnecter pour que `mqtt_connected` soit vrai. Le frontend
continue à signaler les données anciennes selon leur timestamp. La calibration
IsolationForest appartient au service IA et reste en mémoire.

## PostgreSQL

Le même backend utilise PostgreSQL si cette URL est configurée :

```dotenv
DATABASE_URL=postgresql://sentinel:CHANGE_ME@127.0.0.1:5432/sentinel
```

Remplacer les identifiants par ceux de la base. Avec le service `db` du Compose,
renseigner les valeurs `POSTGRES_*` dans le `.env` racine puis lancer uniquement
la base depuis la racine du projet :

```bash
docker compose up -d db
```

L'API sur l'hôte utilise `127.0.0.1:5432`. Une API conteneurisée sur le même
réseau Compose utiliserait `db:5432`. Choisir une autre URL ne transfère pas les
données d'une base vers l'autre. Les tables absentes sont créées sans supprimer
les données existantes ; les évolutions futures du schéma demanderont une migration.

L'accès asynchrone utilise [SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
avec les pilotes `aiosqlite` et `asyncpg`.

## API

Les routes sont disponibles dans **http://localhost:8000/docs**, section
**History**, et reprennent les origines CORS du reste de l'API :

| Route GET | Données |
| --- | --- |
| `/api/v1/history/telemetry` | Température, humidité, gaz, mouvement, appareil |
| `/api/v1/history/vision` | Présence, confiance et source caméra |
| `/api/v1/history/anomalies` | Résultat IsolationForest, score, calibration et caractéristiques |
| `/api/v1/history/alerts` | Alertes avec leur identifiant d'origine |

Chaque réponse contient `items`, `limit` et `next_before_id`. Les événements
les plus récemment enregistrés arrivent en premier, dans un ordre stable par
identifiant. Chaque élément contient `id`, `ts`, `received_at`, `topic` et `data`
(le payload validé, selon le type choisi).

| Paramètre | Comportement |
| --- | --- |
| `limit` | Nombre d'éléments, de 1 à 500 ; défaut 100 |
| `before_id` | Curseur exclusif ; recopier `next_before_id` pour la page suivante |
| `start`, `end` | Bornes inclusives sur `ts`, ISO-8601 avec fuseau ; converties en UTC |
| `device_id` | Filtre exact, uniquement pour la télémétrie |

`next_before_id=null` indique la fin. Les nouvelles publications ne décalent
pas les pages déjà consultées. Les filtres incorrects donnent `422`.

```bash
curl --fail 'http://localhost:8000/api/v1/history/vision?limit=10'
curl --fail 'http://localhost:8000/api/v1/history/telemetry?limit=50&device_id=sentinel-01'
curl --fail 'http://localhost:8000/api/v1/history/anomalies?start=2026-10-07T00:00:00Z&end=2026-10-07T23:59:59Z'
```

## Vérification avec de vraies données

Depuis la racine, après l'installation :

```bash
python3 scripts/local.py start --no-demo
```

Placer une personne devant la webcam puis consulter l'historique vision.
Les historiques capteurs et anomalies restent vides tant qu'aucun capteur réel
n'envoie de télémétrie. Arrêter puis relancer le backend avec la même base
conserve les anciens identifiants et valeurs. Les tests automatisés utilisent
leurs propres bases temporaires et ne peuplent pas la démo.

## Panne et limites

Une base inaccessible empêche le démarrage de l'API. En fonctionnement, une
écriture échouée est réessayée avant d'appliquer le message ; une lecture
d'historique ou la création d'une alerte échouée renvoie `503`.
`/health` renvoie aussi `503` après une opération de stockage échouée.

La file MQTT reste bornée à 128 événements et le contrat utilise QoS 0 : une
coupure prolongée ou un débordement peut perdre des messages. Il n'y a pas de
rejeu durable des publications MQTT, ni de purge automatique de la base.
Lancer un seul processus backend, propriétaire de l'état et des transitions
d'alertes ; multiplier les workers nécessite une coordination supplémentaire.
