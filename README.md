# SENTINEL-X — Workshop M1 2026

Monorepo du prototype SENTINEL-X : surveillance environnementale, détection d'intrusion, dashboard temps réel et sécurisation locale.

## Architecture rapide

```text
DHT22 / MQ-2 / PIR
       │
       ▼
   ESP8266
       │ MQTT / MQTTS
       ▼
 Mosquitto (Raspberry Pi 5)
   ├──────────────► Backend FastAPI (état en mémoire)
   │                    │
   │                    ├── WebSocket/REST ───► React Dashboard
   │                    └── MQTT commands ───► LED/Buzzer via ESP8266
   │
   └──────────────► AI Python (host Pi)
                        ├── Webcam USB → détection personne
                        └── Télémétrie → IsolationForest
                                │
                                └── publie les événements IA sur MQTT
```

## Répartition recommandée

- `feat/infra` : Raspberry Pi 5, Docker, Mosquitto, réseau, MQTTS/TLS, UFW, SSH, PostgreSQL.
- `feat/api-dashboard` : FastAPI, WebSocket/REST, React dashboard ; persistance future.
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
PostgreSQL. FastAPI reçoit la télémétrie et les résultats des deux IA, conserve
120 mesures et 50 alertes au maximum, puis transmet son état au dashboard.
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
- [Configuration et composants du frontend](frontend/README.md).
- [Scénario de présentation](docs/demo-plan.md).

## Vérification avant la démo

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

Puis, depuis la racine dans un autre terminal :

```bash
cd frontend
npm run build
```

Le build vérifie aussi TypeScript et produit `frontend/dist/`.
Les tests backend ne nécessitent pas de broker ; le guide de démo couvre le flux
réel MQTT → IA → API → React et les commandes dans le sens inverse.

L'état, la calibration IA et les historiques sont en mémoire. Un redémarrage
du backend efface son état ; un redémarrage de l'IA relance sa calibration.
Les publications suivantes remplissent à nouveau le dashboard. La confirmation
d'une commande atteste l'envoi MQTT, sans accusé de réception de l'ESP8266.

## Configuration partagée

Le `.env.example` racine reste le catalogue de variables de l'équipe, notamment
pour Docker/PostgreSQL et l'IA. Pour la démo PC, utiliser les exemples propres
à `backend/` et `frontend/` ; le modèle racine contient des identifiants MQTT
destinés à être configurés par l'infrastructure.

Le backend lit `backend/.env`, ou à défaut le `.env` racine. Les variables du
terminal ont priorité. Vite lit `frontend/.env` ; ses variables sont intégrées
au build. Le navigateur communique uniquement avec l'API.

`docker-compose.yml` fournit les services d'infrastructure ; l'API et le frontend
se lancent actuellement sur l'hôte. PostgreSQL, TLS et le déploiement permanent
restent à intégrer avec l'équipe infra. La webcam appartient au service IA.

## Travail dans cette branche

L'implémentation backend/dashboard est sur `feat/api-dashboard`. L'IA validée
est développée séparément sur `feat/ai`. Dans ce workspace, les deux branches
sont ouvertes dans les dossiers voisins `Sentinel-X-api-dashboard/` et
`Sentinel-X/`. Les instructions locales précisent les chemins correspondants.
Les fichiers `.env`, dépendances installées et builds sont ignorés par Git.
Les commits et pushes sont déclenchés uniquement sur demande explicite.

```bash
git status --short
git branch --show-current
```

## Contrat d'intégration

Avant de coder, lire `docs/contracts.md`. C'est la source de vérité commune entre IoT, API, IA et frontend.
