# Dashboard hébergé sur le Raspberry Pi

Le service `frontend` compile React avec Node puis sert uniquement les fichiers
statiques avec Nginx. Il relaie `/api/`, `/health` et `/ws` vers FastAPI.
Le navigateur utilise sa propre origine en production ; les `.env` locaux,
secrets et `node_modules` sont exclus du contexte Docker. Les URL locales de
développement restent inchangées.

Le proxy WebSocket suit les [instructions Nginx](https://nginx.org/en/docs/http/websocket.html).
Il résout de nouveau l'adresse Docker de l'API pour supporter sa recréation.
Les routes React `/environment` et `/vision` sont servies via le même index.
Les fonctions IA existantes ne sont pas activées par ce déploiement.

## Transfert depuis le PC — Git Bash

L'archive `.runtime/frontend-deploy.tar.gz` préparée contient uniquement le
Compose et les sources/configurations publiques du frontend.

```bash
cd ~/Perso/cosmoday-workshop
scp .runtime/frontend-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

Pour la recréer après modification :

```bash
tar --exclude='__pycache__' -czf .runtime/frontend-deploy.tar.gz \
  docker-compose.yml frontend/Dockerfile frontend/.dockerignore frontend/nginx.conf \
  frontend/package.json frontend/package-lock.json frontend/index.html \
  frontend/tsconfig.json frontend/vite.config.ts frontend/src
```

## Sur le Pi — SSH

PostgreSQL et la migration doivent déjà être opérationnels. Ne pas relancer
la migration SQLite pour ajouter le frontend.

```bash
cd ~/cosmoday-workshop
tar -tzf frontend-deploy.tar.gz
tar -xzf frontend-deploy.tar.gz
sudo docker compose --profile api config --quiet
sudo docker compose up -d --build frontend
sudo docker compose ps frontend api db
sudo docker compose logs --tail=40 frontend
curl --fail http://127.0.0.1:8080/frontend-health
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/api/v1/sensors/latest
```

L'API sera recréée si son environnement CORS a changé. Le volume PostgreSQL
et ses données restent conservés. `frontend-health` contrôle Nginx seulement ;
`health` contrôle l'API et sa DB. Le relais MQTT se vérifie avec les mesures.

## Accès depuis le PC

Le port 8080 est lié à `127.0.0.1` sur le Pi. Dans Git Bash, garder ouvert :

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8080:127.0.0.1:8080 sentinelpi1@SentinelPi-1.local
```

Ouvrir **http://localhost:8080**. Aucun serveur Node/Vite n'est requis sur le PC.
Le tunnel 8000 utilisé précédemment peut être fermé s'il n'est plus utile.
REST et WS passent par 8080. Les origines localhost:8080 et 127.0.0.1:8080 sont
explicitement autorisées par FastAPI, même si `.env` garde l'origine Vite.
L'accès LAN direct reste une étape distincte avec authentification et HTTPS.

## Alertes récentes

Les messages ESP reconnus expliquent les seuils franchis : proximité HC-SR04,
seuil gaz MQ-2 calibré, température/humidité hors plage. La proximité ne prouve
pas la présence d'une personne. Le message environnemental ne précise pas le
capteur responsable : aucune valeur historique n'est inventée dans l'affichage.
Les autres messages sont conservés sans cause déduite de mesures plus récentes.
L'IA est annoncée comme une évolution ; ces alertes ne sont pas présentées comme
issues d'une analyse IA. Le contrat MQTT reste inchangé.

## Vérifications

- Les nouvelles mesures changent sans recharger la page (WebSocket).
- Une alerte ESP apparaît avec son explication et une seule entrée.
- Recharger directement `/environment` fonctionne.
- Recréer/redémarrer l'API ne nécessite pas de redémarrer Nginx ; le navigateur
  se reconnecte automatiquement.
- Le dashboard reste disponible après arrêt du serveur Vite local.

Compilation TypeScript/Vite validée localement. Le moteur Docker n'est pas actif
sur le PC : construction ARM64, validation Nginx et proxy REST/WS à confirmer
avec les sorties du Pi.
