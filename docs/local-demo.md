# Démo locale Sentinel-X

## Lancement complet depuis un seul clone

Utiliser la branche `main` pour récupérer backend, frontend et IA
ensemble. Depuis la racine du clone, après les prérequis Linux du README :

```bash
bash scripts/setup_local.sh
python3 scripts/local.py start
```

Le lanceur attend les connexions avant d'envoyer les mesures, garde les services
en arrière-plan et écrit les logs dans `.runtime/`. `status` affiche les
processus ; `stop` ferme uniquement ceux démarrés par le lanceur. Les variables
optionnelles se placent dans `.env.local`, à partir de `local.env.example`.

Sans webcam : utiliser `--no-camera` sur les deux commandes. Pour un ESP réel :
ajouter `--no-demo` au lancement afin de ne pas mélanger les références capteurs.
Le lancement local ne crée ni certificat ni listener MQTT accessible sur le LAN.
Pour le Pi ou le broker infra, suivre le [guide Raspberry](raspberry.md).

Les nouvelles vues sont accessibles sur `/vision` et `/environment`.
Le profil local dérive aussi l'URL du flux caméra et son origine CORS ;
`AI_VISION_STREAM_PORT` permet de changer le port `8765`.

Les instructions détaillées à cinq terminaux ci-dessous restent disponibles
pour observer ou diagnostiquer chaque composant séparément.

## Lancement manuel

Cette procédure utilise le dépôt backend/dashboard sur `feat/api-dashboard` et
le service IA validé, qui peut se trouver dans un worktree séparé sur `feat/ai`.
Les topics et le simulateur restent ceux de [`contracts.md`](contracts.md).

Dans chacun des terminaux, définir les deux chemins en les adaptant à votre
machine ; aucune adresse personnelle n'est nécessaire dans le code :

```bash
export SENTINEL_REPO=/chemin/vers/le-depot-api-dashboard
export SENTINEL_AI_REPO=/chemin/vers/le-depot-ia
```

Si les branches sont déjà intégrées dans un seul dépôt, les deux variables
doivent désigner le même dossier. C'est le cas de `main`.
Les chemins indiquent les racines contenant
respectivement `backend/`, `frontend/` et `ai/`.

## Installation initiale

L'IA dispose déjà de son environnement et de son modèle validés. Pour installer
le backend et le frontend :

```bash
cd "$SENTINEL_REPO/backend"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

Dans un autre terminal :

```bash
cd "$SENTINEL_REPO/frontend"
npm ci
cp -n .env.example .env
```

Les commandes de lancement ci-dessous fixent le broker local à `18883`, sans
identifiants ni TLS. Elles ont priorité sur les valeurs des `.env`.
Pour lancer ensuite l’API sans ces variables de terminal, régler aussi
`MQTT_PORT=18883` dans `backend/.env`.

## Les cinq terminaux

Réutiliser un broker ou un service déjà lancé sur les mêmes ports. Une seule
instance du service IA possède la webcam. Lancer l'IA et attendre son abonnement
à `sentinel/telemetry` avant le simulateur.

Terminal 1 — Mosquitto :

```bash
mosquitto -p 18883 -v
```

Terminal 2 — IA existante :

```bash
cd "$SENTINEL_AI_REPO/ai"
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' AI_TRAINING_SAMPLES=20 \
  .venv/bin/python -m src.main
```

Terminal 3 — API :

```bash
cd "$SENTINEL_REPO/backend"
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' API_HOST=127.0.0.1 API_PORT=8000 \
  CORS_ORIGINS=http://localhost:5173 .venv/bin/python -m app.main
```

Terminal 4 — dashboard :

```bash
cd "$SENTINEL_REPO/frontend"
VITE_API_URL=http://localhost:8000 VITE_WS_URL=ws://localhost:8000/ws \
  VITE_DATA_STALE_SECONDS=30 npm run dev
```

Terminal 5 — télémétrie simulée :

```bash
cd "$SENTINEL_AI_REPO/ai"
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' \
  .venv/bin/python scripts/send_fake_telemetry.py --mode demo
```

Ouvrir **http://localhost:5173**. Le frontend utilise ce nom d'hôte afin de
correspondre exactement à l'origine CORS configurée.

Avec une IA fraîchement démarrée, observer CALIBRATING et un score absent pendant
20 mesures normales, puis ANOMALY et un score numérique sur les cinq valeurs
extrêmes. IsolationForest prend la décision ; le simulateur envoie uniquement
des mesures. Les courbes et l'alerte environnementale apparaissent en temps réel.
La vision validée publie la présence humaine et sa confiance simultanément.

La démo termine ses publications. Après 30 secondes sans nouvelle mesure,
les données concernées deviennent STALE. Pour continuer les mesures :

```bash
cd "$SENTINEL_AI_REPO/ai"
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false \
  MQTT_USERNAME='' MQTT_PASSWORD='' \
  .venv/bin/python scripts/send_fake_telemetry.py --mode normal --count 120
```

Une nouvelle démo ne réentraîne pas un service IA encore actif. Pour présenter
à nouveau la calibration, redémarrer volontairement ce service avant la démo.

## Vérifier les commandes

Dans un terminal supplémentaire :

```bash
mosquitto_sub -h localhost -p 18883 -t sentinel/commands -v
```

Cliquer **ACTIVATE ALARM**, puis **STOP ALARM**. L'abonné doit recevoir
respectivement :

```json
{"buzzer": true, "led": "red"}
{"buzzer": false, "led": "green"}
```

La confirmation affichée atteste l'envoi MQTT. L'action physique LED/buzzer
se vérifie sur l'ESP8266 ; aucun accusé de réception device n'est prévu dans
le contrat actuel. Les boutons sont bloqués pendant l'envoi et hors connexion.

## Diagnostiquer un dashboard vide ou OFFLINE

```bash
curl --fail --silent --show-error http://localhost:8000/health
curl --fail --silent --show-error http://localhost:8000/api/v1/state | python3 -m json.tool
ss -ltnp
```

| Symptôme | Vérification |
| --- | --- |
| Backend CONNECTING, SYSTEM OFFLINE | Lancer l'API et vérifier `/health`. Contrôler les URL dans `frontend/.env` et l'origine CORS. |
| Backend ONLINE, MQTT OFFLINE | Broker démarré sur `18883`, même port dans l'API et l'IA, identifiants cohérents. |
| MQTT CONNECTED, capteurs absents | Lancer le simulateur ou l'ESP ; observer `sentinel/telemetry`. |
| Vision WAITING/STALE | Vérifier le service IA propriétaire de la webcam et ses publications. |
| Environment WAITING | Vérifier l'abonnement IA à la télémétrie et `sentinel/ai/anomaly`. |
| CALIBRATING sans fin | Fournir les 20 mesures normales à une IA démarrée avant la démo. |
| Mesures STALE après la démo | Le simulateur s'est arrêté ; envoyer de nouvelles mesures, ou vérifier les horloges sources. |
| Port déjà utilisé | Réutiliser le service existant ; identifier son processus avec `ss -ltnp`. |

Observer les données brutes si nécessaire :

```bash
mosquitto_sub -h localhost -p 18883 \
  -t sentinel/telemetry -t sentinel/ai/vision -t sentinel/ai/anomaly -v
```

`/health` valide HTTP et signale les échecs de stockage avec `503`. `system.mqtt_connected` dans `/api/v1/state`
valide la connexion MQTT. Des champs IA ou capteurs `null` signifient qu'aucune
donnée valide n'a encore été reçue.

## Reconnexion et limites

Arrêter puis relancer l'API avec les mêmes paramètres : React garde les dernières
lectures pendant la coupure, bloque les commandes, puis se reconnecte sans
recharger la page. L'API recharge les données récentes depuis la même base, puis
reprend les publications suivantes. Une coupure du broker conserve l'état backend ; Paho renouvelle ses
abonnements à la reconnexion.

Lancer un seul processus backend. Plusieurs workers posséderaient chacun un état
en mémoire et pourraient dupliquer les alertes. Le cache temps réel est limité à
120 mesures et 50 alertes ; l'historique complet est consultable dans les
[endpoints de stockage](history.md). Une détection positive répétée ne crée pas de
nouvelle alerte avant un retour à `false`.

## Vérifications reproductibles

```bash
cd "$SENTINEL_REPO/backend"
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Dans un autre terminal :

```bash
cd "$SENTINEL_REPO/frontend"
npm run build
npm run typecheck
```

Les tests backend utilisent un faux client MQTT. Le scénario à cinq terminaux
valide le flux réel. Le contrôle navigateur de l'étape 5 a aussi couvert les
commandes jusqu'à leur réception MQTT, les erreurs d'envoi, les reconnexions,
les timestamps périmés et les écrans desktop/mobile.
