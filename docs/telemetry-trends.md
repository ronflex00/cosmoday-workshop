# Mesures en direct, tendances persistantes

Sur le Pi, `TELEMETRY_STORAGE=trends` remplace l'archivage brut des nouvelles
télémétries par un résumé par minute et par ESP. Le contrat MQTT reste inchangé.
Chaque mesure valide met toujours à jour les cartes, le cache des 120 dernières
mesures et le WebSocket. Aucun changement de firmware n'est nécessaire.

## Contenu enregistré

`sentinel_history.kind = telemetry_trends` contient :

- température, humidité, gaz : moyenne, minimum, maximum ;
- nombre de mesures ;
- présence : au moins une détection, nombre de mesures positives et nombre de
  changements observés dans la minute ;
- identifiant ESP, début de minute UTC et date de stockage.

La minute est celle de réception MQTT, pour grouper les données malgré un
horodatage capteur décalé. Un trou de réception reste un trou, sans interpolation.
Les changements de présence comptés sont ceux observés entre deux mesures de
la même minute : ils ne comptent pas les impulsions entre deux publications.

Une minute close est enregistrée sous cinq secondes environ. Un arrêt normal
enregistre aussi la minute partielle. En cas d'arrêt brutal, la minute encore
en mémoire peut être perdue ; en cas de panne DB, les résumés attendent une
nouvelle tentative. Une reprise dans la même minute complète le résumé déjà
enregistré. Les écritures réessayées ne créent pas une seconde ligne.

À un message toutes les deux secondes, on passe d'environ 43 200 lignes brutes
par jour à au plus 1 440 résumés par ESP/jour. Les résumés sont plus volumineux
qu'une mesure, donc cela ne signifie pas une réduction du disque exactement ×30.
Les résumés continuent de s'accumuler : aucune purge automatique n'est ajoutée.

Les alertes sont conservées individuellement. Les traitements IA existants ne
sont pas modifiés. Les anciennes mesures brutes restent archivées et consultables
via `/api/v1/history/telemetry` ; cette mise à jour ne les supprime pas et ne les
transforme pas rétroactivement.

## Dashboard et API

Les cartes et « Direct · toutes les mesures » utilisent les mesures reçues.
« Historique · moyennes par minute » charge les 120 derniers résumés via
`/api/v1/history/telemetry_trends`, actualisés toutes les trente secondes.
Les infobulles montrent minimum, maximum et nombre de mesures.
L'endpoint accepte les mêmes filtres et pagination que l'historique, y compris
`device_id`, `start`, `end` et `before_id`.

Au redémarrage, le direct attend une vraie mesure : une moyenne persistante
n'est pas affichée comme une température instantanée ou une présence actuelle.
Les tendances déjà enregistrées restent disponibles dans le mode historique.

## Déployer — PC, Git Bash

```bash
cd ~/Perso/cosmoday-workshop
scp .runtime/trends-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

L'archive contient le Compose, les sources API et frontend, sans secret.
Pour la recréer :

```bash
tar --exclude='__pycache__' -czf .runtime/trends-deploy.tar.gz \
  docker-compose.yml backend/Dockerfile backend/.dockerignore backend/requirements.txt backend/app \
  frontend/Dockerfile frontend/.dockerignore frontend/nginx.conf frontend/package.json \
  frontend/package-lock.json frontend/index.html frontend/tsconfig.json frontend/vite.config.ts frontend/src
```

## Sur le Pi

PostgreSQL, MQTT et leurs secrets sont déjà configurés. Ne pas refaire la
migration SQLite ni effacer les volumes.

```bash
cd ~/cosmoday-workshop
tar -tzf trends-deploy.tar.gz
tar -xzf trends-deploy.tar.gz
sudo docker compose --profile api config --quiet
sudo docker compose up -d --build api frontend
sudo docker compose ps api frontend db
curl --fail http://127.0.0.1:8080/health
```

Après une minute complète de mesures :

```bash
curl --fail 'http://127.0.0.1:8080/api/v1/history/telemetry_trends?limit=2'
sudo docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT kind, count(*) FROM sentinel_history GROUP BY kind ORDER BY kind;"'
```

Vérifier que le nombre de lignes `telemetry` ne progresse plus, que les résumés
progressent par minute et que le direct continue toutes les deux secondes.
Redémarrer l'API, vérifier la persistance des tendances et la reprise du direct.
Le tunnel frontend 8080 reste inchangé.

Le mode local `TELEMETRY_STORAGE=raw` conserve la compatibilité des tests et
outils d'historique brut. Les tests couvrent les moyennes/pics/présence, la
reprise d'une minute partielle, les erreurs DB, les appareils distincts, le
direct et le nouvel endpoint. PostgreSQL ARM64 reste à vérifier sur le Pi.
