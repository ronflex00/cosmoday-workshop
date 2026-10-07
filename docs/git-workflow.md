# Workflow Git — sprint 3 jours

Branches permanentes :

- `main` : version complète et démontrable, avec IA, API et dashboards.
- `feat/infra`
- `feat/api-dashboard`
- `feat/ai`
- `feat/firmware`
- `feat/integration` : branche de préparation de l'intégration.

## Récupérer la version intégrée

Nouveau clone :

```bash
git clone --branch main --single-branch https://github.com/ronflex00/cosmoday-workshop.git
cd cosmoday-workshop
bash scripts/setup_local.sh
python3 scripts/local.py start
```

Dans un clone existant dont le travail est sauvegardé :

```bash
git status
git fetch origin
git switch main
git pull --ff-only origin main
```

Si `main` n'existe pas encore localement, utiliser `git switch --track origin/main`
après le fetch. Les branches de spécialité restent séparées ; `main` contient
le backend, les dashboards vision/environnement et l'IA sans dépendre
de dossiers voisins.

## Travail de l'équipe

Règles :

1. `git pull --rebase origin main` avant de commencer une session.
2. Faire des commits petits et explicites : `feat(ai): detect person with webcam`.
3. Pousser au moins toutes les 1 à 2 heures.
4. Fusionner dans `main` à chaque fonctionnalité démontrable.
5. Ne jamais commit `.env`, certificats privés, mots de passe ou modèles lourds.

Exemples de commits :

```text
feat(infra): add mosquitto docker service
feat(api): subscribe to telemetry topic
feat(front): display live sensor cards
feat(ai): add webcam person detection
feat(ai): publish isolation forest result
fix(mqtt): reconnect client after broker restart
security(mqtt): enable TLS listener
```
