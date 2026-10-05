# Backend Sentinel-X

FastAPI reçoit les données MQTT et expose le dernier état par REST et WebSocket. Les contrats
communs sont dans [`../docs/contracts.md`](../docs/contracts.md).

Le client Paho s'abonne automatiquement à :

- `sentinel/telemetry`
- `sentinel/ai/vision`
- `sentinel/ai/anomaly`

Les callbacks MQTT déposent leurs événements dans une file limitée à 128 entrées.
Un consommateur asyncio valide les messages avec Pydantic et met à jour l'état
en mémoire. Les lectures REST et les écritures utilisent la même boucle asyncio.
Les messages incorrects sont ignorés avec un log ; ils ne remplacent pas le
dernier état valide. Les payloads de plus de 16 Kio sont refusés.

L'historique conserve au maximum 120 télémétries dans une `deque`. Aucun serveur
PostgreSQL n'est nécessaire. L'état est perdu au redémarrage du backend ; une
coupure MQTT conserve les dernières données et indique `mqtt_connected=false`.
La reconnexion est automatique et renouvelle les trois abonnements.

Un gestionnaire WebSocket transmet des snapshots complets aux dashboards. Chaque
connexion possède une file d'un seul snapshot en attente : une mise à jour plus
récente remplace celle qui attend. Un envoi qui échoue ou dépasse deux secondes
ferme uniquement le client concerné. La réception MQTT continue indépendamment.

## Installation

Depuis la racine du dépôt, avec Python 3.11 ou supérieur :

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

Les variables du terminal ont priorité sur `.env`. Le backend charge
`backend/.env`, ou à défaut le `.env` de la racine du dépôt.
`requirements.txt` fixe les dépendances directes aux versions validées. Python
3.11 minimum est nécessaire pour la version de `websockets` utilisée.
Pour la démo PC, choisir `MQTT_PORT=18883` dans `backend/.env` ; le modèle
racine contient des paramètres d'infrastructure et n'est pas le profil local.

## Configuration

| Variable | Valeur par défaut | Usage |
| --- | --- | --- |
| `MQTT_HOST` | `localhost` | Adresse du broker |
| `MQTT_PORT` | `1883`, ou `8883` si TLS activé | Port du broker ; `18883` pour la démo PC |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | vides | Identifiants optionnels |
| `MQTT_TLS` | `false` | Activer TLS avec vérification des certificats |
| `MQTT_TLS_CA` | vide | Chemin du certificat CA ; vide utilise les CA système |
| `MQTT_TLS_CERT` / `MQTT_TLS_KEY` | vides | Certificat et clé client, à fournir ensemble |
| `API_HOST` | `127.0.0.1` | Interface HTTP ; utiliser `0.0.0.0` pour un accès réseau |
| `API_PORT` | `8000` | Port HTTP |
| `CORS_ORIGINS` | `http://localhost:5173` | Origines HTTP(S) explicites, séparées par des virgules |
| `API_HISTORY_LIMIT` | `120` | Nombre de points conservés, entre 1 et 120 |

Une origine CORS comprend le protocole, l'hôte et éventuellement le port,
sans chemin ni slash final. Une liste vide désactive l'accès CORS.

## Lancement local

Terminal broker, si aucun broker n'écoute déjà sur ce port :

```bash
mosquitto -p 18883 -v
```

Terminal API, depuis `backend/` :

```bash
source .venv/bin/activate
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' \
  API_HOST=127.0.0.1 API_PORT=8000 python -m app.main
```

Cette commande utilise un seul processus, nécessaire pour l'état en mémoire.
La documentation interactive est disponible sur `http://localhost:8000/docs`.
L'API démarre même si le broker est momentanément indisponible.

## Endpoints disponibles

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/health` | `{"status":"ok"}` ; disponibilité HTTP |
| GET | `/api/v1/state` | État complet, y compris l'historique |
| GET | `/api/v1/status` | État complet, conformément au contrat commun |
| GET | `/api/v1/sensors/latest` | Dernière télémétrie, ou `null` |
| GET | `/api/v1/ai/status` | Objet contenant `vision` et `anomaly` |
| GET | `/api/v1/alerts` | Les 50 dernières alertes au maximum, de la plus récente à la plus ancienne |
| POST | `/api/v1/alerts` | Crée une alerte JSON ; réponse `201` avec un identifiant |
| POST | `/api/v1/commands` | Publie une commande LED/buzzer sur MQTT |
| WS | `/ws` | État initial puis mises à jour complètes |

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/state | python3 -m json.tool
curl -s http://localhost:8000/api/v1/status | python3 -m json.tool
curl -s http://localhost:8000/api/v1/sensors/latest | python3 -m json.tool
curl -s http://localhost:8000/api/v1/ai/status | python3 -m json.tool
```

L'état initial est :

```json
{
  "telemetry": null,
  "vision": null,
  "anomaly": null,
  "system": {"mqtt_connected": false, "last_update": null},
  "history": [],
  "alerts": []
}
```

`last_update` est la date UTC de la dernière donnée valide, alerte créée par REST
ou changement de connexion MQTT traité par le backend. Les timestamps des données sources sont
également conservés. La disponibilité HTTP et la connexion MQTT sont distinctes :
consulter `system.mqtt_connected` pour savoir si le broker est connecté.

## Compatibilité IA

La calibration validée de l'IA est acceptée : `ready=false`, `anomaly=false`,
`score=null`. Après calibration, `ready=true` nécessite un score numérique fini.
L'ancien format du contrat sans `ready` est aussi accepté lorsque le score est
numérique ; le backend l'expose avec `ready=true`. Les valeurs de confiance
vision sont comprises entre 0 et 1, et les timestamps doivent être ISO-8601 UTC.

Dans ce workspace, la branche `feat/api-dashboard` se trouve dans
`Sentinel-X-api-dashboard/` et l'IA validée reste dans le dossier voisin
`Sentinel-X/`, sur `feat/ai`. Pour tester sans modifier la branche IA, démarrer
son service dans un autre terminal, depuis `Sentinel-X/ai/` :

```bash
source .venv/bin/activate
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' python -m src.main
```

Puis lancer le simulateur depuis ce même dossier dans un autre terminal :

```bash
source .venv/bin/activate
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' python scripts/send_fake_telemetry.py --mode demo
```

Les trois services doivent utiliser le même broker. Le simulateur envoie les
mesures ; le service IA calcule les anomalies et publie les résultats. L'API
reçoit ces publications sans accéder à la webcam. Si l'IA tourne déjà sur le
broker choisi, conserver son instance existante. Pour revoir sa calibration,
redémarrer volontairement le service IA avant la démo : son apprentissage reste
en mémoire jusqu'à son arrêt.

## WebSocket sans frontend

Depuis `backend/`, observer les mises à jour avec le client Python installé :

```bash
.venv/bin/python -m websockets ws://localhost:8000/ws
```

Ouvrir deux terminaux avec cette commande permet de tester plusieurs clients.
Le premier message contient l'état courant, ce qui permet aussi à un futur
dashboard de rattraper les changements survenus entre son GET initial et sa
connexion WebSocket. Chaque message utilise cette enveloppe :

```json
{"type": "state", "data": {"telemetry": null, "vision": null, "anomaly": null, "system": {"mqtt_connected": false, "last_update": null}, "history": [], "alerts": []}}
```

Les origines des navigateurs sont vérifiées avec `CORS_ORIGINS`. Un client natif
sans en-tête `Origin`, comme celui ci-dessus, peut aussi se connecter.
Les commandes passent par REST ; les données entrantes sur `/ws` sont ignorées.

## Alertes

Les alertes automatiques sont créées lors de l'activation d'une détection :

- `INTRUSION` : présence humaine, sévérité `critical`.
- `ENVIRONMENTAL_ANOMALY` : anomalie avec `ready=true`, sévérité `warning`.
- `SYSTEM` : MQTT connecté (`info`) ou déconnecté (`warning`).

La première détection positive déclenche aussi une alerte. Les messages
positifs répétés n'en créent pas d'autres ; après un retour à `false`, une
nouvelle activation peut en créer une. La calibration ne génère aucune alerte
environnementale. Les échecs de connexion répétés ne dupliquent pas les alertes
système.

Une `deque` conserve les 50 dernières alertes, incluses dans REST et WebSocket.
Chaque alerte possède un `id`, un timestamp UTC, un `type`, une `severity` et
un `message`. Elles sont publiées sans retain sur `sentinel/alerts`, avec un type
en minuscules et sans identifiant, conformément au contrat MQTT. Cette
publication est facultative pour la conservation locale : si MQTT est hors
ligne, l'alerte reste dans l'historique sans être rejouée à la reconnexion.

Créer manuellement une alerte avec le format du contrat :

```bash
curl -s http://localhost:8000/api/v1/alerts \
  -H 'Content-Type: application/json' \
  -d '{"ts":"2026-10-05T14:30:00Z","type":"intrusion","severity":"critical","message":"Test intrusion"}'
curl -s http://localhost:8000/api/v1/alerts | python3 -m json.tool
```

Le POST accepte les types en minuscules ou majuscules. Sa réponse REST utilise
les types internes en majuscules et ajoute l'identifiant généré par le backend.
Les champs manquants ou incorrects donnent une réponse `422`.

## Commandes LED/buzzer

Dans un terminal, observer les commandes :

```bash
mosquitto_sub -h localhost -p 18883 -t sentinel/commands -v
```

Dans un autre, activer puis arrêter l'alarme :

```bash
curl -s http://localhost:8000/api/v1/commands \
  -H 'Content-Type: application/json' -d '{"buzzer":true,"led":"red"}'
curl -s http://localhost:8000/api/v1/commands \
  -H 'Content-Type: application/json' -d '{"buzzer":false,"led":"green"}'
```

Le payload MQTT contient exactement `buzzer` (booléen) et `led` (`red` ou `green`).
Les champs supplémentaires sont refusés. Une réponse réussie est :

```json
{"status":"published","topic":"sentinel/commands","command":{"buzzer":true,"led":"red"}}
```

La publication utilise QoS 0, sans retain. Le backend attend au maximum deux
secondes la confirmation d'envoi par Paho dans un thread, sans bloquer la boucle
asyncio. Cette réponse confirme l'envoi MQTT ; elle ne confirme pas l'action
physique de l'ESP8266. Une connexion indisponible, un échec ou un délai dépassé
donne `503`. Une commande refusée hors connexion n'est pas conservée pour être
envoyée plus tard. Les détections créent des alertes ; l'activation LED/buzzer
reste commandée explicitement via cet endpoint.

## Tests

Depuis `backend/` :

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m pip check
```

Les tests couvrent les schémas, les messages incorrects, la calibration, les
historiques limités, la file MQTT, la configuration, les endpoints, CORS,
les alertes sans doublons, les commandes hors ligne, les clients WebSocket
multiples, leurs déconnexions et l'isolation d'un client lent ou défaillant.
Ils utilisent un client MQTT simulé et ne nécessitent pas de broker.

L'intégration locale a aussi été vérifiée avec un vrai Mosquitto et Uvicorn,
deux clients WebSocket, le simulateur et IsolationForest de la branche IA :
20 calibrations puis 5 anomalies, publications des alertes et commandes,
redémarrage du broker et arrêt propre du service.

Le [dashboard React](../frontend/README.md) est disponible. La
[démo locale complète](../docs/local-demo.md) fournit les cinq terminaux et le
diagnostic des connexions ; le [guide Raspberry](../docs/raspberry.md) précise
les adresses navigateur, l'écoute réseau et les origines CORS.
