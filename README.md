# SENTINEL-X — Workshop M1 2026

Monorepo du prototype SENTINEL-X : surveillance environnementale, détection d'intrusion, dashboard temps réel et sécurisation locale.

## Récupérer et lancer la version complète

La branche **`main`** réunit le backend, les dashboards et l'IA validée.
Un seul clone suffit ; aucun worktree voisin ni chemin personnel n'est requis.

Prérequis : **Linux**, **Python 3.11+**, **Node.js 20.19+ dans la série 20, ou 22.12+**,
`npm`, `mosquitto`, `mosquitto_sub` et une webcam pour la vision. Les bibliothèques
système OpenCV GL/GLib sont détaillées dans [ai/README.md](ai/README.md).
Une connexion Internet est nécessaire pour la première installation des
dépendances et du modèle YOLO. Aucun GPU ni PostgreSQL n'est requis.

Sur Debian/Ubuntu, installer `python3-venv`, `mosquitto` et
`mosquitto-clients` avec le gestionnaire système avant le script. Installer
aussi les bibliothèques GL/GLib pour le mode webcam. Node et npm doivent être
disponibles dans les versions indiquées ci-dessus.

```bash
git clone --branch main --single-branch https://github.com/ronflex00/cosmoday-workshop.git
cd cosmoday-workshop
bash scripts/setup_local.sh
python3 scripts/local.py start
```

Ouvrir **http://localhost:5173**. Le lanceur démarre Mosquitto (`18883`),
FastAPI (`8000`), React (`5173`), YOLO sur la webcam et IsolationForest.
Il attend l'abonnement IA avant de démarrer les capteurs simulés : 20 mesures
normales, puis cinq valeurs extrêmes, répétées sous l'identifiant `sentinel-demo`.
La décision d'anomalie vient du modèle. Les services restent en arrière-plan.

Les pages **http://localhost:5173/vision** et
**http://localhost:5173/environment** affichent respectivement le flux caméra
annoté et le suivi environnemental avec l'historique des scores IA. Le service
IA fournit le flux MJPEG et ses métriques sur le port local `8765`.

```bash
python3 scripts/local.py status
python3 scripts/local.py stop
```

Les logs sont dans `.runtime/`. Le stop concerne uniquement les processus
démarrés par ce lanceur ; un broker préexistant réutilisé est conservé.
Les ports API/frontend déjà occupés sont signalés, sans arrêter leur propriétaire.

Sans webcam, installation et lancement plus légers :

```bash
bash scripts/setup_local.sh --no-camera
python3 scripts/local.py start --no-camera
```

Ce mode conserve la télémétrie, IsolationForest, le dashboard et les commandes.
Le panneau vision reste en attente ; aucune détection caméra fictive n'est publiée.
Pour utiliser les mesures d'un ESP à la place du simulateur, ajouter `--no-demo`.
LED/buzzer nécessitent le matériel connecté ; le dashboard confirme l'envoi MQTT.

Configuration optionnelle, sans modifier le code :

```bash
cp -n local.env.example .env.local
```

Modifier hôte/port MQTT, ports API/frontend/vision, index caméra ou paramètres IA dans
`.env.local`, puis arrêter et relancer le lanceur. Les variables du terminal
ont priorité. Les URL API/WebSocket/vision et CORS suivent les ports configurés, sauf
override explicite. Le profil local est distinct du `.env` racine destiné à
l'infrastructure ; les profils réels, logs, venvs, dépendances et poids du modèle
sont ignorés par Git.

## Architecture rapide

```text
DHT22 / MQ-2 / PIR
       │
       ▼
   ESP8266
       │ MQTT / MQTTS
       ▼
 Mosquitto (Raspberry Pi 5)
   ├──────────────► Backend FastAPI (cache temps réel)
   │                    │
   │                    ├── WebSocket/REST ───► React Dashboard
   │                    ├── MQTT commands ───► LED/Buzzer via ESP8266
   │                    └── Historique ──────► SQLite / PostgreSQL
   │
   └──────────────► AI Python (host Pi)
                        ├── Webcam USB → détection personne
                        └── Télémétrie → IsolationForest
                                │
                                └── publie les événements IA sur MQTT
```

## Répartition recommandée

- `feat/infra` : Raspberry Pi 5, Docker, Mosquitto, réseau, MQTTS/TLS, UFW, SSH, PostgreSQL.
- `feat/api-dashboard` : FastAPI, WebSocket/REST, React dashboard et historique en base.
- `feat/ai` : webcam, OpenCV/YOLO, IsolationForest, publication MQTT des résultats IA.
- `feat/firmware` : ESP8266, capteurs, OLED, LED, buzzer, MQTT.

## Priorités 3 jours

1. Jour 1 : bout-en-bout minimal `ESP -> MQTT -> API -> Dashboard` + webcam ouverte côté IA.
2. Jour 2 : détection personne + anomalie + alertes dashboard + commandes LED/buzzer.
3. Jour 3 : MQTTS/TLS, hardening, stabilité, boîtier, documentation et répétition démo.

## Règle Git

`main` doit rester démontrable. Travaillez uniquement sur les branches `feat/*`, faites de petits commits et fusionnez plusieurs fois par jour au lieu d'attendre la fin.

## Backend et dashboard disponibles

La V1 fonctionne sur un PC Linux avec Mosquitto local, sans Raspberry ni
PostgreSQL. FastAPI reçoit la télémétrie et les résultats des deux IA, les enregistre
en base et transmet son état au dashboard. Le cache contient jusqu'à 120 mesures
et 50 alertes ; l'historique complet est consultable par l'API.
React charge d'abord REST, puis suit les mises à jour WebSocket avec reconnexion.
Les commandes LED/buzzer passent par REST puis MQTT.

Le dashboard affiche les quatre capteurs, la présence humaine et sa confiance,
CALIBRATING/NORMAL/ANOMALY avec le score IsolationForest, les courbes et les
alertes. Les résultats absents ou périmés sont signalés et les commandes sont
désactivées si le backend ou MQTT est indisponible.

Prérequis : **Python 3.11+**, **Node.js 20.19+ dans la série 20, ou 22.12+**,
Mosquitto et ses clients. Les dépendances directes Python sont fixées aux
versions validées ; `npm ci` utilise le verrouillage des dépendances frontend.

Installation API, depuis la racine du dépôt :

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

Pour la démo PC, régler `MQTT_PORT=18883` dans `backend/.env`. Les identifiants
restent vides pour le broker local sans authentification.

Installation frontend, depuis la racine du dépôt :

```bash
cd frontend
npm ci
cp -n .env.example .env
```

Lancement API, depuis `backend/` :

```bash
.venv/bin/python -m app.main
```

Lancement dashboard, depuis `frontend/` :

```bash
npm run dev
```

Ouvrir **http://localhost:5173** ; l'API et sa documentation sont accessibles sur
**http://localhost:8000/docs**. Le broker et le service IA existant doivent
tourner sur le même port que le backend.

- [Démo locale : cinq terminaux et diagnostic](docs/local-demo.md).
- [Intégration Raspberry Pi et accès depuis un autre PC](docs/raspberry.md).
- [Configuration et endpoints du backend](backend/README.md).
- [Base de données et API des historiques](docs/history.md).
- [Configuration et composants du frontend](frontend/README.md).
- [Scénario de présentation](docs/demo-plan.md).

## Vérification avant la démo

Depuis la racine, après l'installation complète avec webcam :

```bash
python3 -m unittest discover -s tests -v
(cd ai && .venv/bin/python -m unittest discover -s tests -v)
(cd backend && .venv/bin/python -m unittest discover -s tests -v)
(cd frontend && npm run build)
```

Cela couvre les 22 tests IA, les 46 tests backend, les deux tests de propriété
des processus du lanceur et le build TypeScript/React. Les tests IA importent
la vision ; ils nécessitent donc l'installation complète, même sans webcam
branchée. L'installation `--no-camera` suffit pour les tests backend et lanceur.

Pour vérifier le flux réel, lancer la démo et observer l'état reçu :

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/api/v1/state
mosquitto_sub -h localhost -p 18883 -t sentinel/ai/anomaly -v
```

Adapter les ports si `.env.local` a été personnalisé. Dans le dashboard,
la télémétrie apparaît puis l'IA passe de CALIBRATING à NORMAL/ANOMALY après
20 mesures. Les boutons publient sur `sentinel/commands` ; le lanceur écrit
ces messages dans `.runtime/events.log` avec le profil local par défaut.
Le build produit `frontend/dist/`. Les tests unitaires ne nécessitent pas de
broker ; le guide de démo couvre le flux MQTT → IA → API → React et les commandes.

La télémétrie, les résultats des IA et les alertes sont conservés en base. Le
backend recharge ses données récentes au redémarrage. La calibration du modèle
IA reste en mémoire : redémarrer l'IA relance son apprentissage. La confirmation
d'une commande atteste l'envoi MQTT, sans accusé de réception de l'ESP8266.

## Configuration partagée

Le `.env.example` racine reste le catalogue de variables de l'équipe, notamment
pour Docker/PostgreSQL et l'IA. Pour la démo PC, utiliser les exemples propres
à `backend/` et `frontend/` ; le modèle racine contient des identifiants MQTT
destinés à être configurés par l'infrastructure.

Le backend lit `backend/.env`, ou à défaut le `.env` racine. Les variables du
terminal ont priorité. Vite lit `frontend/.env` ; ses variables sont intégrées
au build. Le navigateur utilise l'API pour l'état et les commandes, et le
service IA pour le flux caméra et ses métriques.

`docker-compose.yml` fournit les services d'infrastructure ; l'API et le frontend
se lancent actuellement sur l'hôte. PostgreSQL est configurable avec `DATABASE_URL` ;
la démo locale utilise SQLite. TLS et le déploiement permanent restent à intégrer
avec l'équipe infra. La webcam appartient au service IA.

## Travail dans cette branche

`main` est la version complète à récupérer pour lancer la démo, y compris les
nouveaux dashboards vision et environnement.
Les branches `feat/api-dashboard`, `feat/ai` et `feat/integration` conservent
leurs développements séparés. `main` contient leurs historiques, et n'ajoute
aucune dépendance au Raspberry pour une démonstration sur PC.
Les fichiers `.env`, dépendances installées et builds sont ignorés par Git.
Les commits et pushes sont déclenchés uniquement sur demande explicite.

```bash
git status --short
git branch --show-current
```

## Contrat d'intégration

Avant de coder, lire `docs/contracts.md`. C'est la source de vérité commune entre IoT, API, IA et frontend.
