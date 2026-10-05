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
   ├──────────────► Backend FastAPI ───► PostgreSQL
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
- `feat/api-dashboard` : FastAPI, WebSocket/REST, persistance, React dashboard.
- `feat/ai` : webcam, OpenCV/YOLO, IsolationForest, publication MQTT des résultats IA.
- `feat/firmware` : ESP8266, capteurs, OLED, LED, buzzer, MQTT.

## Priorités 3 jours

1. Jour 1 : bout-en-bout minimal `ESP -> MQTT -> API -> Dashboard` + webcam ouverte côté IA.
2. Jour 2 : détection personne + anomalie + alertes dashboard + commandes LED/buzzer.
3. Jour 3 : MQTTS/TLS, hardening, stabilité, boîtier, documentation et répétition démo.

## Règle Git

`main` doit rester démontrable. Travaillez uniquement sur les branches `feat/*`, faites de petits commits et fusionnez plusieurs fois par jour au lieu d'attendre la fin.

## Démarrage GitHub

Créez un dépôt GitHub vide nommé `sentinel-x`, puis :

```bash
git remote add origin git@github.com:VOTRE-ORG-OU-USER/sentinel-x.git
git push -u origin main
git push --all origin
```

## Contrat d'intégration

Avant de coder, lire `docs/contracts.md`. C'est la source de vérité commune entre IoT, API, IA et frontend.
