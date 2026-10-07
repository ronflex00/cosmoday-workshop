# PostgreSQL sur le Raspberry Pi

Le Compose utilise maintenant PostgreSQL 16 pour toute la persistance de l'API.
SQLite reste disponible pour les tests locaux et comme source de migration.
Les mesures et alertes résident dans `postgres_data`. L'état ESP reste un état
courant MQTT, pas un historique en base. PostgreSQL ne publie aucun port réseau.
Le mot de passe est un fichier privé partagé en lecture seule avec l'API.
Cette méthode est supportée par [l'image officielle PostgreSQL](https://hub.docker.com/_/postgres).

## 1. Transfert — PC, Git Bash

```bash
cd ~/Perso/cosmoday-workshop
mkdir -p .runtime
tar --exclude='__pycache__' -czf .runtime/postgres-deploy.tar.gz \
  docker-compose.yml backend/Dockerfile backend/.dockerignore \
  backend/requirements.txt backend/app
scp .runtime/postgres-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

## 2. Préparation — terminal SSH du Pi

Avant extraction, sauvegarder le Compose SQLite pour retour arrière. Le nom
de sauvegarde est daté ; conserver le chemin affiché.

```bash
cd ~/cosmoday-workshop
rollback_compose="docker-compose.sqlite-$(date -u +%Y%m%dT%H%M%SZ).yml"
cp --no-clobber docker-compose.yml "$rollback_compose"
printf 'Compose de retour arrière : %s\n' "$rollback_compose"
sudo docker compose ps db
sudo docker volume ls --filter name=cosmoday-workshop_postgres_data
```

Si PostgreSQL a déjà été initialisé, son mot de passe existant doit être repris.
La variable `POSTGRES_PASSWORD_FILE` ne change pas le mot de passe d'une base
existante. Ne jamais supprimer le volume pour résoudre un problème d'accès.
Dans notre déploiement précédent, seul MQTT et l'API SQLite ont été lancés.

Créer le fichier uniquement s'il n'existe pas, en saisissant un mot de passe
PostgreSQL dédié. `set -C` évite tout écrasement accidentel.

```bash
mkdir -p secrets/db
chmod 700 secrets/db
(
  umask 077
  set -C
  read -r -s -p 'Mot de passe PostgreSQL : ' postgres_password
  printf '\n'
  printf '%s\n' "$postgres_password" > secrets/db/password
  unset postgres_password
)
sudo chown 10001:10001 secrets/db/password
sudo chmod 600 secrets/db/password
tar -tzf postgres-deploy.tar.gz
tar -xzf postgres-deploy.tar.gz
sudo docker compose --profile api config --quiet
```

`POSTGRES_USER` et `POSTGRES_DB` sont repris du `.env` existant, ou valent
`sentinel` par défaut. `POSTGRES_PASSWORD` du `.env` n'est plus utilisé par
ces services. Ne pas afficher les fichiers privés.

## 3. Migration — Pi

L'ESP peut rester allumé, mais les messages reçus pendant l'arrêt de l'API
ne seront pas archivés. Faire cette étape pendant une courte fenêtre de test.

```bash
sudo docker compose stop api
sudo docker compose up -d --wait db
sudo docker compose build api
sudo docker compose run --rm --no-deps api python -m app.migrate_sqlite
```

Le script affiche le fichier `sentinel-backup-….db` créé dans `api_data`, puis
`Migration committed: … rows`. Il conserve les IDs, dates et payloads de toutes
les catégories. Une destination non vide provoque un refus ; une erreur annule
les insertions. La séquence PostgreSQL est recalée pour les futures écritures.
Ne pas démarrer l'API si la migration échoue : examiner la sortie d'abord.
Une migration réussie n'est à lancer qu'une fois.

```bash
sudo docker compose up -d api
sudo docker compose ps api db
sudo docker compose logs --tail=40 api
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/api/v1/sensors/latest
sudo docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT kind, count(*) FROM sentinel_history GROUP BY kind ORDER BY kind;"'
```

Observer les nouvelles mesures et alertes sur le dashboard via le tunnel SSH
existant. Redémarrer `api db`, attendre leur santé, puis vérifier que l'historique
reste présent et que le nombre de télémétries augmente : cela valide les écritures
dans PostgreSQL, au-delà du seul contrôle `/health`.

## Sauvegarde PostgreSQL

```bash
mkdir -p secrets/backups
chmod 700 secrets/backups
(
  umask 077
  sudo docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "secrets/backups/sentinel-$(date -u +%Y%m%dT%H%M%SZ).dump"
)
```

Conserver aussi une copie des sauvegardes hors du Pi : le volume Docker protège
du remplacement de conteneur, pas d'une panne de carte SD. Ne pas lancer `down -v`.

## Retour arrière

Si la bascule échoue, arrêter l'API et rétablir le Compose SQLite sauvegardé,
puis `docker compose up -d api`. Le fichier SQLite et son volume sont conservés.
Les données écrites exclusivement dans PostgreSQL après la bascule ne sont pas
recopiées automatiquement dans SQLite ; sauvegarder PostgreSQL avant un retour.

## Validation

Les tests locaux contrôlent la copie SQLite, le refus d'une destination non vide,
la conservation des IDs et l'encodage du secret. La migration réelle, la séquence
PostgreSQL et la persistance ARM64 doivent être confirmées avec les sorties du Pi.
