# Intégration API/dashboard sur Raspberry Pi

Ce guide concerne `feat/api-dashboard`. Le broker, les certificats, les règles
réseau, le service IA et le firmware restent gérés par leurs équipes. Les
commandes Raspberry sont une procédure d'intégration ; leur exécution sur
matériel ARM n'a pas été validée par les tests PC.

## Prérequis et installation de l'API

Utiliser Raspberry Pi OS 64 bits, Python **3.11+** et un broker déjà configuré.
Le projet doit être disponible sur le Pi avec la branche backend/dashboard.
Créer l'environnement Python sur le Pi ; celui du PC n'est pas portable entre
les architectures. La [documentation Raspberry Pi OS](https://www.raspberrypi.com/documentation/computers/os.html)
décrit l'utilisation des environnements virtuels pour les paquets Python.

Depuis la racine du dépôt sur le Pi :

```bash
python3 --version
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
```

Installer `python3-venv` avec le gestionnaire de paquets de l'OS si le module
`venv` n'est pas disponible. Le backend utilise Uvicorn comme serveur ASGI,
conformément au [lancement manuel FastAPI](https://fastapi.tiangolo.com/deployment/manually/).

## Option A : API sur le Pi, frontend sur le PC

Remplacer `sentinel.local` par le nom réseau réel du Pi ou son adresse IP.
Depuis le Pi, `hostname -I` permet d'afficher ses adresses locales.

Dans `backend/.env` sur le Pi, pour un broker local sans TLS ni authentification :

```dotenv
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TLS=false
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:5173
API_HISTORY_LIMIT=120
```

Les paramètres MQTT doivent correspondre au broker fourni par l'infrastructure.
Si le broker écoute sur `18883` ou impose des identifiants, adapter ces valeurs.
Le broker local `mosquitto -p 18883` du PC sert à la démo sur ce PC ; son écoute
sur loopback ne fournit pas un broker accessible aux appareils du réseau.

Lancer l'API depuis `backend/` sur le Pi :

```bash
.venv/bin/python -m app.main
```

Depuis le PC, vérifier HTTP :

```bash
curl --fail --silent --show-error http://sentinel.local:8000/health
```

Dans `frontend/.env` sur le PC :

```dotenv
VITE_API_URL=http://sentinel.local:8000
VITE_WS_URL=ws://sentinel.local:8000/ws
VITE_DATA_STALE_SECONDS=30
```

Depuis `frontend/` sur le PC :

```bash
npm ci
npm run dev
```

Ouvrir `http://localhost:5173` sur le PC. L'origine du frontend reste donc
`http://localhost:5173`, ce qui correspond au `CORS_ORIGINS` du Pi. Les URL de
l'API sont résolues par le navigateur sur le PC : `localhost:8000` désignerait
le PC, et non le Pi.

### Partager le frontend du PC sur le LAN

Si le jury ouvre le frontend depuis un autre appareil, démarrer Vite sur le PC :

```bash
npm run dev -- --host 0.0.0.0
```

Par exemple, pour un PC `192.168.10.20` et un Pi `192.168.10.1`, ouvrir
`http://192.168.10.20:5173`. Dans le `.env` backend du Pi :

```dotenv
CORS_ORIGINS=http://192.168.10.20:5173,http://localhost:5173
```

Dans le `.env` frontend du PC :

```dotenv
VITE_API_URL=http://192.168.10.1:8000
VITE_WS_URL=ws://192.168.10.1:8000/ws
```

Ces adresses sont des exemples à remplacer par celles du réseau de démo.
Relancer l'API après un changement CORS et Vite après un changement de ses URL.
Les paramètres se changent uniquement dans l'environnement ; le code reste
identique. L'origine CORS correspond à l'URL ouverte dans le navigateur, et non
à l'adresse de l'API ou du broker. L'équipe infra doit permettre les connexions
aux ports choisis entre les appareils du réseau.

## Option B : API et build frontend sur le Pi

Prévoir Node.js **20.19+ dans la série 20, ou 22.12+** pour construire le frontend.
Le build peut également être produit sur le PC puis son dossier `dist/` copié
sur le Pi. Seuls les fichiers statiques sont nécessaires à leur diffusion.

Dans `frontend/.env` avant le build :

```dotenv
VITE_API_URL=http://sentinel.local:8000
VITE_WS_URL=ws://sentinel.local:8000/ws
VITE_DATA_STALE_SECONDS=30
```

Dans `backend/.env`, régler l'origine exacte de la page qui sera ouverte :

```dotenv
API_HOST=0.0.0.0
CORS_ORIGINS=http://sentinel.local:5173
```

Depuis `frontend/`, construire et servir pour la démonstration LAN :

```bash
npm ci
npm run build
python3 -m http.server 5173 --bind 0.0.0.0 --directory dist
```

Redémarrer l'API après avoir changé son `.env`. Ouvrir
`http://sentinel.local:5173` depuis le PC. Si le navigateur utilise une IP à la
place du nom réseau, remplacer aussi cette origine dans `CORS_ORIGINS` et les URL
de build. Plusieurs origines explicites peuvent être séparées par des virgules.

Vite intègre `VITE_*` dans le build : changer les adresses impose de reconstruire
`dist/`. Pour un hébergement permanent, l'équipe infra peut servir ce dossier
via son serveur HTTP. `npm run preview` est un outil de vérification locale,
selon la [documentation de déploiement Vite](https://vite.dev/guide/static-deploy.html).

## MQTT avec TLS existant

Lorsque l'infrastructure fournit un listener TLS et les certificats :

```dotenv
MQTT_HOST=sentinel.local
MQTT_PORT=8883
MQTT_TLS=true
MQTT_USERNAME=sentinel
MQTT_PASSWORD=REMPLACER_PAR_LE_SECRET_FOURNI
MQTT_TLS_CA=/chemin/fourni-par-infra/ca.crt
```

Si le broker exige un certificat client, renseigner ensemble `MQTT_TLS_CERT`
et `MQTT_TLS_KEY`. Le nom `MQTT_HOST` doit correspondre au certificat serveur.
La vérification TLS reste activée ; aucun fichier de certificat ni règle réseau
n'est créé par cette branche. MQTT TLS est indépendant de HTTPS pour le dashboard.
Pour une page HTTPS, configurer aussi une API HTTPS et un WebSocket `wss://`.

## Validation avec l'équipe

1. Vérifier `/health`, puis `system.mqtt_connected` dans `/api/v1/state`.
2. Faire publier l'ESP ou le simulateur IA sur `sentinel/telemetry` et observer
   les cartes et les courbes.
3. Vérifier CALIBRATING puis NORMAL/ANOMALY avec le service IA existant.
4. Vérifier les résultats vision sans lancer un second propriétaire de la caméra.
5. Observer `sentinel/commands` lors des deux boutons, puis vérifier LED/buzzer
   sur le matériel.
6. Couper puis relancer API et broker pour vérifier les deux reconnexions.

Conserver **un seul processus API** tant que l'état est en mémoire. PostgreSQL
n'est pas requis pour cette V1. Les détections IA génèrent des alertes ; elles
n'activent pas automatiquement le buzzer. La commande doit être explicitement
envoyée et sa confirmation ne constitue pas un retour d'état de l'ESP8266.

## Vérifications avant transfert

Depuis `backend/` :

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Depuis `frontend/` :

```bash
npm ci
npm run typecheck
npm run build
```

Les dépendances runtime fixées ont été vérifiées avec PyPI : les paquets natifs
[`websockets`](https://pypi.org/project/websockets/17.2/#files) et
[`pydantic-core`](https://pypi.org/project/pydantic-core/2.46.5/#files) fournissent
des wheels Linux ARM64 pour Python 3.11. Une résolution à blanc de toutes les
dépendances sur cette cible a réussi
sans compilation. Le code backend ne dépend ni de GPU, ni de webcam, ni de
fonctionnalité x86. Sur le matériel, valider encore l'installation native,
les origines et ports LAN, la configuration TLS fournie et l'effet LED/buzzer.

Commande de résolution exécutée depuis `backend/` sur le PC, sans installation :

```bash
.venv/bin/python -m pip install --dry-run --ignore-installed \
  --only-binary=:all: --platform manylinux2014_aarch64 \
  --python-version 3.11 --implementation cp --abi cp311 \
  -r requirements.txt
```
