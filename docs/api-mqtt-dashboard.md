# ESP → MQTTS → FastAPI → dashboard admin

Cette étape concerne l'exposition des mesures, alertes et état ESP. Aucun
service IA ni contrôleur automatique n'est ajouté ou lancé.

## Données et interfaces

| Topic | Validation | Exposition |
| --- | --- | --- |
| `sentinel/telemetry` | Télémétrie du contrat | `/api/v1/sensors/latest`, historique, état REST et WS |
| `sentinel/status/device` | Identifiant, online ; IP/RSSI requis quand online | Champ `device` dans `/api/v1/status`, `/api/v1/state`, `/ws` |
| `sentinel/alerts` | Timestamp UTC, type, sévérité, message | `/api/v1/alerts`, historique des alertes, état REST et WS |

Les abonnements IA déjà existants sont conservés pour compatibilité, sans
modification de leur traitement dans cette étape. L'état appareil n'est pas
confondu avec la connexion API au broker. Le dashboard affiche maintenant
un état ESP séparé ; les valeurs absentées restent inconnues.

Les alertes MQTT reçues ne sont jamais republiées. Les échos des alertes
produites par les endpoints existants sont ignorés. Les événements externes
identiques (timestamp, type, sévérité, message) ont une identité stable pour
éviter des doublons dans l'historique. Deux alertes identiques dans la même
seconde sont donc considérées comme le même événement : le contrat actuel
ne fournit pas d'identifiant d'événement.

## Persistance utilisée pour cette étape

Le backend existant supporte PostgreSQL et SQLite via `DATABASE_URL`.
Le service Compose `api` utilise explicitement SQLite dans
`/app/data/sentinel.db`, conservé dans le volume `api_data`. Les mesures et
alertes persistent au redémarrage du conteneur. Le statut ESP reste un état
courant, reçu du broker (retained/Last Will), sans historique DB dans cette étape.

PostgreSQL reste la cible finale du projet ; il n'est pas démarré par
`docker compose up -d api`. Son déploiement et sa migration seront traités
séparément. Ne pas utiliser `docker compose down -v` : cela effacerait les volumes.

## Accès administrateur

Le conteneur API écoute en interne sur 8000, publié uniquement sur
`127.0.0.1:8000` du Pi. Le PC admin passe par un tunnel SSH authentifié par
clé. Le navigateur ne reçoit aucun secret MQTT, ne contacte jamais le broker
et communique avec FastAPI via REST/WebSocket.

Ce mode protège l'accès réseau par SSH pendant l'intégration. L'API ne dispose
pas encore d'une authentification applicative pour un dashboard multiutilisateur.
Un hébergement LAN permanent avec HTTPS/WSS et authentification sera une étape
distincte. Conserver le bind loopback tant que cette protection n'est pas prête.

## Transférer les fichiers sans secrets (PC, Git Bash)

Depuis la racine du projet, après validation du code :

```bash
mkdir -p .runtime
tar --exclude='__pycache__' -czf .runtime/api-deploy.tar.gz \
  docker-compose.yml backend/Dockerfile backend/.dockerignore \
  backend/requirements.txt backend/app
scp .runtime/api-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

Le paquet ne contient ni firmware/config.h, ni `.env`, ni certificat privé,
ni mot de passe. Sur le Pi, vérifier le contenu avant extraction :

```bash
cd ~/cosmoday-workshop
tar -tzf api-deploy.tar.gz
tar -xzf api-deploy.tar.gz
```

Les fichiers broker existants et ses secrets ne sont pas dans ce paquet.
Le `.env` racine déjà utilisé par Compose reste requis par le service DB.

## Préparer le secret API (Pi)

Vérifier si le fichier existe avant de le créer. Ne pas afficher son contenu.

```bash
cd ~/cosmoday-workshop
ls -l secrets/api/mqtt_password
```

Si absent, créer le fichier en saisissant le mot de passe déjà créé pour
`sentinel-api`, pas celui de l'ESP :

```bash
mkdir -p secrets/api
chmod 700 secrets/api
(
  umask 077
  set -C
  read -r -s -p 'Mot de passe MQTT sentinel-api : ' api_mqtt_password
  printf '\n'
  printf '%s\n' "$api_mqtt_password" > secrets/api/mqtt_password
  unset api_mqtt_password
)
sudo chown 10001:10001 secrets/api/mqtt_password
sudo chmod 600 secrets/api/mqtt_password
```

L'utilisateur du conteneur est `10001:10001`. Le mot de passe est monté seul,
en lecture seule, sans monter le fichier des comptes du broker ni ses clés.
La CA publique est également montée seule ; `MQTT_HOST=mqtt` correspond au
SAN `DNS:mqtt` du certificat créé pendant les tests.

## Démarrer et vérifier l'API (Pi)

```bash
sudo docker compose --profile api config --quiet
sudo docker compose up -d --build api
sudo docker compose ps api
sudo docker compose logs --tail=50 api
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/api/v1/status
curl --fail http://127.0.0.1:8000/api/v1/sensors/latest
curl --fail http://127.0.0.1:8000/api/v1/alerts
```

Attendre une mesure de l'ESP. Vérifier `system.mqtt_connected=true`,
`device.online=true` et les mesures réelles. `/health` vérifie l'API et la DB,
pas la connexion MQTT : contrôler les deux séparément. Le healthcheck Compose
doit devenir healthy. L'image tourne sans root, sans capacités supplémentaires,
avec le filesystem en lecture seule et un volume de données en écriture.

## Relier le dashboard (PC)

Dans un terminal PC, garder le tunnel ouvert :

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8000:127.0.0.1:8000 sentinelpi1@SentinelPi-1.local
```

Ne pas lancer d'API locale concurrente sur le même port. Si 8000 est occupé,
choisir un autre port local et modifier les deux URL frontend en conséquence.
Inspecter `frontend/.env` avant modification ; créer à partir de l'exemple
uniquement s'il est absent. Pour le tunnel par défaut :

```dotenv
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

Dans un autre terminal PC :

```bash
cd frontend
npm ci
npm run dev
```

Ouvrir `http://localhost:5173`. L'origine doit être autorisée par `CORS_ORIGINS`
du Compose. REST fournit l'état initial ; WebSocket fournit ensuite les mises
à jour et se reconnecte automatiquement. Les pages IA peuvent rester en attente.

## Test bout en bout

1. Observer température/humidité/gaz/présence réels et courbes dans le dashboard.
2. Déclencher une proximité HC-SR04 : alerte locale dans `/api/v1/alerts`,
   historique et dashboard, sans boucle ni republication.
3. Débrancher/rebrancher l'ESP : le statut ESP change, sans confondre ce cas
   avec une panne du broker.
4. Redémarrer l'API : historique conservé, statut de nouveau reçu via retained,
   WebSocket reconnecté. Observer les nouveaux points après redémarrage.

Ne déclarer ces étapes validées qu'après les sorties réelles du Pi et les
observations du navigateur. Les tests automatisés utilisent MQTT simulé et
SQLite ; la construction ARM64 de l'image reste à confirmer sur le Pi.
